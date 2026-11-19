"""Tablas de salida (CSV completos + Markdown legible)."""
from __future__ import annotations

from pathlib import Path
from typing import List

import numpy as np
import pandas as pd


def _fmt(v, nd=3):
    if isinstance(v, (float, np.floating)):
        return "—" if not np.isfinite(v) else f"{v:.{nd}f}"
    return "—" if v is None or (isinstance(v, str) and v == "") else str(v)


def to_markdown(df: pd.DataFrame, cols: List[str], headers: List[str], nd: int = 3) -> str:
    lines = ["| " + " | ".join(headers) + " |", "|" + "|".join(["---"] * len(headers)) + "|"]
    for _, r in df[cols].iterrows():
        lines.append("| " + " | ".join(_fmt(r[c], nd) for c in cols) + " |")
    return "\n".join(lines)


MD_COLS = [
    ("scenario", "Esc."), ("rep", "Rep."), ("series", "Serie"), ("delta_s", "Δ (s)"),
    ("udp_loss", "Pérdida UDP"), ("capture_drops", "Descartes captura"),
    ("range_s", "Tramo (s)"), ("n_scales", "n"), ("beta", "β̂"), ("H", "Ĥ"), ("r2", "R²"),
    ("sens_max_abs_dH", "máx |ΔĤ| sens."), ("perm_H_median", "Ĥ perm. med."),
    ("perm_H_range", "Ĥ perm. [mín, máx]"), ("control_result", "Control"), ("status", "Estado"),
]


def write_summary(summary: pd.DataFrame, outdir: Path) -> None:
    outdir.mkdir(parents=True, exist_ok=True)
    summary.to_csv(outdir / "summary.csv", index=False)
    s = summary.copy()
    for c in ("udp_loss", "capture_drops"):
        if c not in s:
            s[c] = "—"
    s["perm_H_range"] = [
        "—" if not np.isfinite(a) else f"[{a:.3f}, {b:.3f}]" for a, b in zip(s["perm_H_min"], s["perm_H_max"])
    ]
    md = ["# Resumen — autosimilitud en trazas LAN", "",
          "Tabla completa (incluye IC95% indicativo, semillas, excluidas, diagnósticos) en `summary.csv`.", "",
          to_markdown(s, [c for c, _ in MD_COLS], [h for _, h in MD_COLS]), ""]
    bad = s[s["status"] != "estimado"]
    if len(bad):
        md += ["## Series sin estimación sustentada", ""]
        md += [f"- **{r.run} · {r.series} · Δ={r.delta_s} s**: {r.reason}" for r in bad.itertuples()]
        md.append("")
    (outdir / "summary.md").write_text("\n".join(md), encoding="utf-8")


def robustness_table(summary: pd.DataFrame, curves: pd.DataFrame, cfg) -> pd.DataFrame:
    """Compara Ĥ entre Δ (misma repetición) y entre repeticiones (mismo Δ), y
    la diferencia relativa de Var(tasa) en escalas físicas comunes."""
    rows = []
    d0, d1 = cfg.base_delta_s, cfg.robust_delta_s
    for (scen, ser), g in summary.groupby(["scenario", "series"]):
        for rep, gr in g.groupby("rep"):
            h0 = gr.loc[np.isclose(gr["delta_s"], d0), "H"]
            h1 = gr.loc[np.isclose(gr["delta_s"], d1), "H"]
            run_id = gr["run"].iloc[0]
            c0 = curves[(curves["run"] == run_id) & (curves["series"] == ser)]
            a = c0[np.isclose(c0["delta_s"], d0) & c0["valid"]]
            b = c0[np.isclose(c0["delta_s"], d1) & c0["valid"]]
            a = a.set_index(a["scale_s"].round(6))
            b = b.set_index(b["scale_s"].round(6))
            common = a.index.intersection(b.index)
            rel = (np.abs(a.loc[common, "V_rate"] - b.loc[common, "V_rate"]) / a.loc[common, "V_rate"]).max() \
                if len(common) else np.nan
            rows.append({"comparison": f"Δ {d0} vs {d1}", "scenario": scen, "series": ser, "fixed": rep,
                         "H_1": h0.iloc[0] if len(h0) else np.nan, "H_2": h1.iloc[0] if len(h1) else np.nan,
                         "common_scales_s": f"{min(common):g}–{max(common):g}" if len(common) else "—",
                         "max_rel_diff_Vrate_common": rel})
        for d, gd in g.groupby("delta_s"):
            reps = sorted(gd["rep"].unique())
            if len(reps) >= 2:
                h = gd.set_index("rep")["H"]
                rows.append({"comparison": f"{reps[0]} vs {reps[1]}", "scenario": scen, "series": ser,
                             "fixed": f"Δ={d}", "H_1": h[reps[0]], "H_2": h[reps[1]],
                             "common_scales_s": "—", "max_rel_diff_Vrate_common": np.nan})
    df = pd.DataFrame(rows)
    if len(df):
        df["dH"] = df["H_2"] - df["H_1"]
    return df
