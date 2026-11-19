#!/usr/bin/env python3
"""
Laboratorio "Autosimilitud en trazas de tráfico LAN" — análisis reproducible.

Desde los CSV exportados con TShark (frame.time_epoch, frame.len, ip.src,
udp.dstport) reconstruye las series regulares, estima H por varianza
agregada, contrasta con 30 permutaciones, repite con Δ = 0.10 s y genera
figuras (PNG 300 DPI + PDF) y tablas.

Ejemplos
--------
  python run_analysis.py data/raw/                       # todos los CSV del directorio
  python run_analysis.py data/raw/E1_R1.csv data/raw/E2_*.csv \\
         --windows data/meta/windows.csv --schedule data/meta/schedule.csv \\
         --meta data/meta/runs.csv --out outputs
  python run_analysis.py data/raw/ --fit-range 0.1:6.4   # mismo tramo físico en todo

Los nombres de archivo deben contener escenario y repetición: E1_R1.csv, E2_R2.csv, …
"""
from __future__ import annotations

import argparse
import glob
import hashlib
import json
import logging
import platform
import sys
from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd

from autosim import plots
from autosim.config import SCENARIO_SERIES, AnalysisConfig
from autosim.control import control_verdict, derived_seed, permutation_control
from autosim.hurst import estimate_hurst, variance_time
from autosim.report import robustness_table, write_summary
from autosim.spectrum import periodogram_control
from autosim.series import (activity_summary, bin_bytes, determine_t0, flow_masks,
                            on_segments, silence_stats, trend_stats)
from autosim.trace_io import (NS, parse_run_name, read_metadata, read_schedule,
                              read_trace, read_windows)

log = logging.getLogger("autosim")


# --------------------------------------------------------------------------
# CLI
# --------------------------------------------------------------------------
def parse_args(argv=None) -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("inputs", nargs="+", help="CSV de TShark, directorios o patrones glob")
    p.add_argument("--windows", type=Path, help="CSV run,t0[,duration_s] (t0 en epoch del reloj de C)")
    p.add_argument("--schedule", type=Path, help="CSV run,source,start_s,end_s (cronograma E2, s desde t0)")
    p.add_argument("--meta", type=Path, help="CSV run,udp_loss,capture_drops[,…] (se anexa al resumen)")
    p.add_argument("--out", type=Path, default=Path("outputs"), help="carpeta de salida (def. outputs)")
    p.add_argument("--seed", type=int, default=AnalysisConfig.seed, help="semilla base de permutaciones")
    p.add_argument("--n-perm", type=int, default=AnalysisConfig.n_perm)
    p.add_argument("--fit-range", type=str, default=None,
                   help="fija el tramo en segundos 'lo:hi' (p. ej. 0.1:6.4); por defecto automático")
    p.add_argument("--r2-min", type=float, default=None, help="umbral R² adicional (desactivado por defecto)")
    p.add_argument("--max-rmse", type=float, default=AnalysisConfig.max_rmse_dex,
                   help="RMSE máx. de residuos en décadas de log10 V (def. 0.03)")
    p.add_argument("--max-local-dev", type=float, default=AnalysisConfig.max_local_slope_dev)
    p.add_argument("--formats", default="png,pdf", help="formatos de figura, p. ej. png,pdf")
    p.add_argument("--dpi", type=int, default=AnalysisConfig.dpi)
    p.add_argument("--no-nominal", action="store_true", help="no dibujar la tasa nominal en E1")
    p.add_argument("-v", "--verbose", action="store_true")
    return p.parse_args(argv)


def collect_inputs(items) -> list[Path]:
    paths: list[Path] = []
    for it in items:
        pth = Path(it)
        if pth.is_dir():
            paths += sorted(pth.glob("*.csv"))
        elif any(ch in it for ch in "*?["):
            paths += [Path(x) for x in sorted(glob.glob(it))]
        else:
            paths.append(pth)
    uniq = list(dict.fromkeys(p.resolve() for p in paths))
    if not uniq:
        sys.exit("No se encontraron CSV de entrada.")
    for p in uniq:
        if not p.exists():
            sys.exit(f"No existe: {p}")
    return uniq


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def ns_to_epoch_str(ns: int) -> str:
    return f"{ns // NS}.{ns % NS:09d}"


# --------------------------------------------------------------------------
# Análisis de una corrida
# --------------------------------------------------------------------------
def analyze_run(path: Path, cfg: AnalysisConfig, windows, schedule, figdir: Path) -> dict:
    run, scen, rep = parse_run_name(path)
    if scen not in SCENARIO_SERIES:
        raise ValueError(f"Escenario desconocido {scen} en {path.name}")
    df = read_trace(path)
    masks, n_unexpected = flow_masks(df, scen)
    t0, t0_src = determine_t0(df, masks, scen, run, windows)
    t_all, L_all = df["t_ns"].to_numpy(), df["length"].to_numpy()
    series_names = SCENARIO_SERIES[scen]
    log.info("%s: %d paquetes, t0=%s (%s)", run, len(df), ns_to_epoch_str(t0), t0_src)

    summary, curves, cands, robust = [], [], [], []
    X_base, warnings = {}, []
    info_main = None

    for delta in cfg.deltas:
        results = {}
        for s in series_names:
            X, info = bin_bytes(t_all[masks[s]], L_all[masks[s]], t0, delta, cfg.window_s)
            if s == series_names[0] and delta == cfg.base_delta_s:
                info_main = info
                if info["packets_in"] == 0:
                    raise ValueError(
                        f"{run}: ningún paquete de la serie {s} cae en la ventana [t0, t0 + {cfg.window_s:g} s) "
                        f"con t0 = {ns_to_epoch_str(t0)} ({t0_src}). Revise el t0 de esta corrida en "
                        "windows.csv: debe ser el epoch del reloj de C al iniciar la ventana.")
            if delta == cfg.base_delta_s:
                X_base[s] = X
            vt = variance_time(X, delta, cfg.scales, cfg.min_blocks)
            est = estimate_hurst(vt, cfg)
            fit = est["fit"]
            seed = derived_seed(cfg.seed, f"{run}|{s}|{delta:.2f}")
            ctl = permutation_control(X, vt, fit if est["status"] == "estimado" else None, cfg.n_perm, seed)
            results[s] = {"vt": vt, "est": est, "ctl": ctl}
            robust.append({"rep": rep, "delta": delta, "series": s, "vt": vt, "ctl": ctl, "scenario": scen})

            Hhat = fit["H"] if est["status"] == "estimado" else np.nan
            Hp = ctl["H_perm"]
            valid = vt["valid"].to_numpy()
            sil = silence_stats(X, delta)
            tr = trend_stats(X, delta)
            summary.append({
                "scenario": scen, "rep": rep, "run": run, "series": s, "delta_s": delta,
                "N": info["N"], "t0_source": t0_src, "packets": info["packets_in"],
                "bytes": info["bytes_in"], "mean_rate_Mbps": info["bytes_in"] * 8 / cfg.window_s / 1e6,
                "zero_frac": sil["zero_frac"], "longest_silence_s": sil["longest_silence_s"],
                "trend_pct_per_100s": tr["trend_pct_per_100s"], "trend_p": tr["trend_p"],
                "excluded_scales": "; ".join(f"m={r.m} ({r.excluded_reason})"
                                             for r in vt[~vt["valid"]].itertuples()) or "ninguna",
                "fit_mode": est["mode"], "status": est["status"], "reason": est["reason"],
                "range_s": f"{fit['s_lo']:g}–{fit['s_hi']:g}" if fit else "—",
                "range_m": f"{fit['m_lo']}–{fit['m_hi']}" if fit else "—",
                "n_scales": fit["n_scales"] if fit else np.nan,
                "beta": fit["beta"] if fit else np.nan, "beta_se": fit["beta_se"] if fit else np.nan,
                "H": Hhat, "H_ci95_lo": fit["H_ci_lo"] if fit and np.isfinite(Hhat) else np.nan,
                "H_ci95_hi": fit["H_ci_hi"] if fit and np.isfinite(Hhat) else np.nan,
                "r2": fit["r2"] if fit else np.nan,
                "max_local_slope_dev": fit["max_local_dev"] if fit else np.nan,
                "rmse_dex": fit["rmse_dex"] if fit else np.nan,
                "sens_drop_first_H": est["sens_drop_first_H"], "sens_drop_last_H": est["sens_drop_last_H"],
                "sens_max_abs_dH": est["sens_max_abs_dH"],
                "perm_n": cfg.n_perm, "perm_seed": seed,
                "perm_H_median": np.nanmedian(Hp) if np.isfinite(Hp).any() else np.nan,
                "perm_H_min": np.nanmin(Hp) if np.isfinite(Hp).any() else np.nan,
                "perm_H_max": np.nanmax(Hp) if np.isfinite(Hp).any() else np.nan,
                "perm_H_q25": np.nanquantile(Hp, 0.25) if np.isfinite(Hp).any() else np.nan,
                "perm_H_q75": np.nanquantile(Hp, 0.75) if np.isfinite(Hp).any() else np.nan,
                "control_result": control_verdict(Hhat, Hp),
                "log10_ratio_V_vs_perm_at_max_valid_scale":
                    ctl["log10_ratio"][valid][-1] if valid.any() else np.nan,
            })
            in_fit = np.zeros(len(vt), bool)
            if fit:
                in_fit[fit["i0"]: fit["i1"] + 1] = True
            for j, r in enumerate(vt.itertuples()):
                curves.append({
                    "run": run, "scenario": scen, "rep": rep, "series": s, "delta_s": delta,
                    "m": r.m, "scale_s": r.scale_s, "M": r.M, "V": r.V, "V_rate": r.V_rate,
                    "valid": r.valid, "excluded_reason": r.excluded_reason, "in_fit": bool(in_fit[j]),
                    "perm_V_median": ctl["V_med"][j], "perm_V_q25": ctl["V_q25"][j],
                    "perm_V_q75": ctl["V_q75"][j], "perm_V_min": ctl["V_min"][j],
                    "perm_V_max": ctl["V_max"][j], "log10_ratio_V_vs_perm": ctl["log10_ratio"][j],
                })
            for c in est["candidates"]:
                cands.append({"run": run, "series": s, "delta_s": delta,
                              "chosen": bool(fit is not None and c["i0"] == fit["i0"] and c["i1"] == fit["i1"]),
                              **{k: v for k, v in c.items() if k not in ("i0", "i1")}})

        fig = plots.plot_variance_time(run, scen, rep, delta, results, cfg)
        plots.save(fig, figdir, f"vt_{run}_d{int(round(delta * 100)):03d}", cfg)

    # --- series temporales y actividad (Δ base)
    observed = declared = None
    activity = None
    N = int(round(cfg.window_s / cfg.base_delta_s))
    if scen == "E2":
        observed = {k: on_segments(X_base[k], cfg.base_delta_s, cfg.on_gap_merge_s) for k in ("A", "B")}
        sch = schedule[schedule["run"] == run]
        declared = {k: sch.loc[sch["source"] == k, ["start_s", "end_s"]].to_numpy(float) for k in ("A", "B")}
        if sch.empty:
            declared = None
        activity = {"run": run, **activity_summary(observed["A"], observed["B"], N, cfg.base_delta_s, declared)}
    fig = plots.plot_timeseries(run, scen, rep, X_base, cfg.base_delta_s, cfg, t0_src, observed, declared)
    plots.save(fig, figdir, f"ts_{run}", cfg)

    # --- periodicidad (Δ base): periodograma frente al control permutado
    spec = {}
    for s in series_names:
        f, p, ctrl, peak = periodogram_control(X_base[s], cfg.base_delta_s, cfg.n_perm,
                                               derived_seed(cfg.seed, f"{run}|{s}|psd"))
        spec[s] = {"f": f, "p": p, "ctrl": ctrl, "peak": peak}
        for row in summary:
            if row["series"] == s:
                row.update({"psd_peak_Hz": peak["freq_Hz"], "psd_peak_period_s": peak["period_s"],
                            "psd_peak_prominence_dec": peak["prominence_dec"],
                            "psd_peak_above_ctrl_dec": peak["above_ctrl_dec"]})
    fig = plots.plot_periodogram(run, scen, rep, cfg.base_delta_s, spec, cfg)
    plots.save(fig, figdir, f"psd_{run}", cfg)

    # --- controles de calidad de la ventana
    if info_main["packets_before"]:
        warnings.append(f"{info_main['packets_before']} paquetes antes de t0")
    if scen == "E1" and info_main["last_rel_s"] < cfg.window_s - 1.0:
        warnings.append(f"el flujo termina en {info_main['last_rel_s']:.1f} s (< {cfg.window_s:g} s): "
                        "ceros finales artificiales")
    if n_unexpected:
        warnings.append(f"{n_unexpected} paquetes con origen/puerto no esperado (excluidos)")
    for w in warnings:
        log.warning("%s: %s", run, w)

    run_info = {
        "run": run, "scenario": scen, "rep": rep, "file": path.name, "sha256": sha256(path),
        "t0_epoch": ns_to_epoch_str(t0), "t0_source": t0_src, "window_s": cfg.window_s,
        "packets_total_csv": len(df), "packets_unexpected": n_unexpected,
        "main_packets_in_window": info_main["packets_in"], "main_packets_before_t0": info_main["packets_before"],
        "main_packets_after_window": info_main["packets_after"],
        "main_first_rel_s": info_main["first_rel_s"], "main_last_rel_s": info_main["last_rel_s"],
        "warnings": " | ".join(warnings),
    }
    return {"summary": summary, "curves": curves, "cands": cands, "robust": robust,
            "activity": activity, "info": run_info}


# --------------------------------------------------------------------------
# Principal
# --------------------------------------------------------------------------
def main(argv=None) -> int:
    args = parse_args(argv)
    logging.basicConfig(level=logging.DEBUG if args.verbose else logging.INFO,
                        format="%(levelname)-7s %(message)s")
    logging.getLogger("fontTools").setLevel(logging.WARNING)     # silencia el subsetting del PDF
    fit_range = None
    if args.fit_range:
        lo, hi = (float(x) for x in args.fit_range.split(":"))
        fit_range = (lo, hi)
    cfg = replace(AnalysisConfig(), seed=args.seed, n_perm=args.n_perm, fit_range_s=fit_range,
                  r2_min=args.r2_min, max_rmse_dex=args.max_rmse, max_local_slope_dev=args.max_local_dev, dpi=args.dpi,
                  formats=tuple(f.strip() for f in args.formats.split(",") if f.strip()),
                  nominal_frame_rate_Bps=None if args.no_nominal else AnalysisConfig.nominal_frame_rate_Bps)

    figdir, tabdir = args.out / "figures", args.out / "tables"
    plots.apply_style()
    windows = read_windows(args.windows)
    schedule = read_schedule(args.schedule)
    meta = read_metadata(args.meta)

    S, C, K, R, A, I = [], [], [], [], [], []
    for path in collect_inputs(args.inputs):
        out = analyze_run(path, cfg, windows, schedule, figdir)
        S += out["summary"]; C += out["curves"]; K += out["cands"]; R += out["robust"]; I.append(out["info"])
        if out["activity"]:
            A.append(out["activity"])

    summary = pd.DataFrame(S)
    if len(meta.columns) > 1:
        summary = summary.merge(meta, on="run", how="left")
    curves = pd.DataFrame(C)

    # --- figuras de robustez y resumen
    for scen in sorted({r["scenario"] for r in R}):
        fig = plots.plot_robust_variance(scen, [r for r in R if r["scenario"] == scen], cfg)
        plots.save(fig, figdir, f"robust_{scen}", cfg)
    plots.save(plots.plot_h_summary(summary, cfg), figdir, "H_summary", cfg)

    # --- tablas
    tabdir.mkdir(parents=True, exist_ok=True)
    write_summary(summary, tabdir)
    curves.to_csv(tabdir / "variance_curves.csv", index=False)
    pd.DataFrame(K).to_csv(tabdir / "fit_candidates.csv", index=False)
    pd.DataFrame(I).to_csv(tabdir / "run_info.csv", index=False)
    rob = robustness_table(summary, curves, cfg)
    rob.to_csv(tabdir / "robustness.csv", index=False)
    if A:
        pd.DataFrame(A).to_csv(tabdir / "activity_E2.csv", index=False)

    import matplotlib, scipy  # noqa: E401
    params = {
        "generated_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "config": cfg.as_dict(),
        "seed_derivation": "SeedSequence([seed_base, crc32('<run>|<serie>|<Δ con 2 decimales>')])",
        "inputs": [{"file": i["file"], "sha256": i["sha256"]} for i in I],
        "auxiliary": {k: str(v) if v else None for k, v in
                      (("windows", args.windows), ("schedule", args.schedule), ("meta", args.meta))},
        "versions": {"python": platform.python_version(), "numpy": np.__version__, "pandas": pd.__version__,
                     "scipy": scipy.__version__, "matplotlib": matplotlib.__version__},
    }
    (args.out / "params.json").write_text(json.dumps(params, indent=2, ensure_ascii=False), encoding="utf-8")

    # --- resumen en consola
    cols = ["run", "series", "delta_s", "range_s", "beta", "H", "r2", "perm_H_median", "control_result"]
    with pd.option_context("display.width", 160, "display.max_columns", 20, "display.precision", 3):
        print("\n" + summary[cols].to_string(index=False))
    print(f"\nFiguras: {figdir}\nTablas:  {tabdir}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
