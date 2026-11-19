"""
Figuras del laboratorio. Todas se guardan sin interacción (backend Agg) en
PNG 300 DPI y PDF vectorial.

Codificación visual (fija en todo el proyecto, nunca cíclica)
-------------------------------------------------------------
Serie   A  -> azul Okabe-Ito      #0072B2
        B  -> bermellón           #D55E00
        A+B-> verde azulado       #009E73
Repetición R1 -> gris casi negro #222222 ; R2 -> púrpura #AA3377
Δ = 0.05 s -> línea continua + círculo relleno
Δ = 0.10 s -> línea discontinua + cuadrado hueco
Control permutado -> gris neutro (mediana discontinua + bandas IQR y mín–máx)
Referencia H = 0.5 (pendiente -1) -> púrpura rojizo, trazo-punto
La paleta de series se verificó para daltonismo (deuteranopía/protanopía/
tritanopía) y el color nunca es la única pista: hay leyenda, marcadores y
títulos de panel.
"""
from __future__ import annotations

from pathlib import Path
from typing import Dict, List, Optional

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402
from matplotlib.lines import Line2D  # noqa: E402
from matplotlib.patches import Patch  # noqa: E402
from matplotlib.ticker import FixedLocator, FuncFormatter, NullFormatter  # noqa: E402

from .config import SOURCES  # noqa: E402
from .series import rate_series  # noqa: E402

SERIES_COLORS = {"A": "#0072B2", "B": "#D55E00", "A+B": "#009E73"}
REP_COLORS = {"R1": "#222222", "R2": "#AA3377"}
CONTROL = "#8C8C8C"
REF = "#CC79A7"
INK = "#222222"
MUTED = "#5F5F5F"
DELTA_STYLE = {0.05: dict(ls="-", marker="o", mfc=None), 0.10: dict(ls="--", marker="s", mfc="none")}


def apply_style() -> None:
    plt.rcParams.update({
        "font.family": "DejaVu Sans",
        "font.size": 9,
        "axes.titlesize": 10,
        "axes.titleweight": "bold",
        "axes.labelsize": 9,
        "axes.labelcolor": INK,
        "axes.edgecolor": "#9A9A9A",
        "axes.linewidth": 0.8,
        "axes.spines.top": False,
        "axes.spines.right": False,
        "axes.grid": True,
        "grid.alpha": 0.25,
        "grid.linewidth": 0.6,
        "xtick.color": MUTED,
        "ytick.color": MUTED,
        "xtick.labelsize": 8,
        "ytick.labelsize": 8,
        "legend.fontsize": 8,
        "legend.frameon": False,
        "figure.facecolor": "white",
        "savefig.facecolor": "white",
        "pdf.fonttype": 42,          # texto editable en el PDF
        "ps.fonttype": 42,
    })


def save(fig, outdir: Path, name: str, cfg) -> List[Path]:
    outdir.mkdir(parents=True, exist_ok=True)
    paths = []
    for fmt in cfg.formats:
        p = outdir / f"{name}.{fmt}"
        fig.savefig(p, dpi=cfg.dpi, bbox_inches="tight")
        paths.append(p)
    plt.close(fig)
    return paths


def _fmt_delta(d: float) -> str:
    return f"{d:.2f}".rstrip("0").rstrip(".") if d >= 0.1 else f"{d:.2f}"


def _step_xy(t: np.ndarray, y: np.ndarray, width: float):
    """Extiende la escalera hasta el final del último bloque."""
    return np.r_[t, t[-1] + width], np.r_[y, y[-1]]


def _series_label(s: str) -> str:
    if s == "A+B":
        return "A+B (agregado)"
    ip, port = SOURCES[s]
    return f"{s} ({ip} → :{port})"


# ==========================================================================
# 1) Series temporales multi-escala (bytes/s)
# ==========================================================================
def plot_timeseries(run: str, scen: str, rep: str, X: Dict[str, np.ndarray], delta: float,
                    cfg, t0_note: str, observed: Optional[Dict[str, np.ndarray]] = None,
                    declared: Optional[Dict[str, np.ndarray]] = None):
    res = list(cfg.ts_resolutions_s)
    ms = [int(round(r / delta)) for r in res]
    for r, m in zip(res, ms):
        if abs(m * delta - r) > 1e-9:
            raise ValueError(f"La resolución {r} s no es múltiplo de Δ={delta} s")

    is_e2 = scen == "E2"
    nrows = len(res) + (1 if is_e2 else 0)
    ratios = ([0.62] if is_e2 else []) + [1.0] * len(res)
    fig, axes = plt.subplots(nrows, 1, figsize=(11, 1.9 * nrows + 0.6), sharex=True,
                             gridspec_kw={"height_ratios": ratios}, constrained_layout=True)
    axes = np.atleast_1d(axes)
    T = cfg.window_s

    # --- franja de actividad (E2): cronograma declarado vs ráfagas observadas
    if is_e2:
        ax = axes[0]
        lanes = []
        for src in ("A", "B"):
            if declared and src in declared and len(declared[src]):
                lanes.append((f"{src} declarado", declared[src], SERIES_COLORS[src], "decl"))
            lanes.append((f"{src} observado", observed[src], SERIES_COLORS[src], "obs"))
        both = _intersect(observed["A"], observed["B"])
        lanes.append(("A y B a la vez", both, SERIES_COLORS["A+B"], "obs"))
        for i, (lab, segs, col, kind) in enumerate(lanes):
            y = len(lanes) - 1 - i
            xr = [(a, b - a) for a, b in segs]
            if kind == "decl":
                ax.broken_barh(xr, (y - 0.32, 0.64), facecolors="none", edgecolors=col,
                               hatch="////", linewidth=0.6)
            else:
                ax.broken_barh(xr, (y - 0.32, 0.64), facecolors=col, alpha=0.9, linewidth=0)
        ax.set_yticks(range(len(lanes)))
        ax.set_yticklabels([l[0] for l in lanes][::-1])
        ax.set_ylim(-0.6, len(lanes) - 0.4)
        ax.grid(axis="y", visible=False)
        ax.tick_params(axis="y", length=0)
        ax.set_title(f"Cronograma de ráfagas · ON observado = intervalos con tráfico a Δ = {delta} s, "
                     f"uniendo silencios < {cfg.on_gap_merge_s} s", loc="left",
                     fontsize=8.5, fontweight="normal", color=MUTED)

    rate_axes = axes[1:] if is_e2 else axes
    ymax = 0.0
    for ax, r, m in zip(rate_axes, res, ms):
        if is_e2:
            tA, rA = rate_series(X["A"], delta, m)
            _, rB = rate_series(X["B"], delta, m)
            x, yA = _step_xy(tA, rA, m * delta)
            _, yT = _step_xy(tA, rA + rB, m * delta)
            ax.fill_between(x, 0, yA, step="post", color=SERIES_COLORS["A"], alpha=0.8, lw=0,
                            label=_series_label("A"))
            ax.fill_between(x, yA, yT, step="post", color=SERIES_COLORS["B"], alpha=0.8, lw=0,
                            label=_series_label("B"))
            ax.step(x, yT, where="post", color=INK, lw=0.5, label="A+B (total)")
            total = rA + rB
        else:
            t, rr = rate_series(X["A"], delta, m)
            x, y = _step_xy(t, rr, m * delta)
            ax.fill_between(x, 0, y, step="post", color=SERIES_COLORS["A"], alpha=0.15, lw=0)
            ax.step(x, y, where="post", color=SERIES_COLORS["A"], lw=0.7, label=_series_label("A"))
            total = rr
        if cfg.nominal_frame_rate_Bps and not is_e2:
            ax.axhline(cfg.nominal_frame_rate_Bps, color=MUTED, lw=0.9, ls=(0, (4, 3)),
                       label="tasa nominal de trama (iperf3 -b 4M -l 1200)")
        ymax = max(ymax, float(np.max(total)) if total.size else 0)
        mu, sd = float(total.mean()), float(total.std(ddof=1))
        cv = sd / mu if mu > 0 else np.nan
        tail = T - (T / delta // m) * m * delta
        ax.text(0.004, 0.96,
                f"Resolución {r:g} s  (m = {m}, {total.size} bloques"
                + (f", se descartan {tail:.2f} s finales" if tail > 1e-9 else "")
                + f")   ·   media {mu * 8 / 1e6:.3f} Mbit/s   ·   CV = σ/μ = {cv:.3f}",
                transform=ax.transAxes, va="top", ha="left", fontsize=8, color=INK,
                bbox=dict(boxstyle="round,pad=0.25", fc="white", ec="none", alpha=0.85))
        ax.set_ylabel("bytes/s")
        ax.yaxis.set_major_formatter(FuncFormatter(lambda v, _: f"{v / 1e3:,.0f}k" if v else "0"))

    for ax in rate_axes:                # misma escala vertical: magnitudes comparables
        ax.set_ylim(0, ymax * 1.18 if ymax > 0 else 1)
    axes[-1].set_xlim(0, T)
    axes[-1].set_xlabel("Tiempo desde t0 (s)")
    h, l = rate_axes[0].get_legend_handles_labels()
    fig.legend(h, l, loc="lower center", ncol=len(l), bbox_to_anchor=(0.5, -0.035 if is_e2 else -0.05))

    fig.suptitle(f"{scen} · {rep} — tasa recibida en C (bytes de trama por segundo) "
                 f"en {len(res)} resoluciones", x=0.0, ha="left", fontsize=12, fontweight="bold")
    axes[0].annotate(f"Ventana {T:g} s desde t0 ({t0_note}) · Δ base = {delta} s · bloques completos "
                     f"no solapados · eje vertical común",
                     xy=(0, 1), xycoords="axes fraction", xytext=(0, 22 if is_e2 else 8),
                     textcoords="offset points", fontsize=8.5, color=MUTED, va="bottom")
    return fig


def _intersect(a: np.ndarray, b: np.ndarray) -> List[tuple]:
    out, i, j = [], 0, 0
    a, b = np.asarray(a).reshape(-1, 2), np.asarray(b).reshape(-1, 2)
    while i < len(a) and j < len(b):
        lo, hi = max(a[i, 0], b[j, 0]), min(a[i, 1], b[j, 1])
        if hi > lo:
            out.append((lo, hi))
        if a[i, 1] < b[j, 1]:
            i += 1
        else:
            j += 1
    return out


# ==========================================================================
# 2) Varianza agregada log–log + control
# ==========================================================================
def plot_variance_time(run: str, scen: str, rep: str, delta: float, results: Dict[str, dict], cfg):
    names = list(results)
    fig, axes = plt.subplots(1, len(names), figsize=(max(4.6 * len(names) + 0.6, 7.4), 4.9 if len(names) > 1 else 5.6),
                             squeeze=False, constrained_layout=True)
    for ax, s in zip(axes[0], names):
        _vt_panel(ax, s, delta, results[s], cfg)

    handles = [
        Line2D([], [], ls="none", marker="o", color=INK, mec="white", ms=7, label="escala incluida en el ajuste"),
        Line2D([], [], ls="none", marker="o", mfc="none", mec=INK, ms=7, label="válida, fuera del tramo"),
        Line2D([], [], ls="none", marker="x", color=CONTROL, ms=7, label=f"excluida (M < {cfg.min_blocks})"),
        Line2D([], [], color=INK, lw=2, label="recta OLS en el tramo (sombreado)"),
        Line2D([], [], color=REF, lw=1.3, ls=(0, (5, 2, 1, 2)), label="referencia independencia: pendiente −1 (H = 0.5)"),
        Line2D([], [], color=CONTROL, lw=1.2, ls="--", label=f"mediana de {cfg.n_perm} permutaciones"),
        Patch(fc=CONTROL, alpha=0.45, label="control: IQR"),
        Patch(fc=CONTROL, alpha=0.18, label="control: mín–máx"),
    ]
    one = len(names) == 1
    fig.legend(handles=handles, loc="lower center", ncol=2 if one else 4,
               bbox_to_anchor=(0.5, -0.17 if one else -0.13))
    N = int(round(cfg.window_s / delta))
    fig.suptitle(f"{scen} · {rep} — varianza agregada  ·  Δ = {delta} s, ventana {cfg.window_s:g} s "
                 f"(N = {N})", x=0.0, ha="left",
                 fontsize=12, fontweight="bold")
    return fig


def _vt_panel(ax, s: str, delta: float, R: dict, cfg):
    vt, est, ctl = R["vt"], R["est"], R["ctl"]
    col = SERIES_COLORS[s]
    x_all = np.log10(vt["scale_s"].to_numpy())
    V = vt["V"].to_numpy()
    pos = np.isfinite(V) & (V > 0)

    # Control permutado (bandas sobre todas las escalas con varianza > 0)
    okc = ctl["V_min"] > 0
    ax.fill_between(x_all[okc], np.log10(ctl["V_min"][okc]), np.log10(ctl["V_max"][okc]),
                    color=CONTROL, alpha=0.18, lw=0)
    ax.fill_between(x_all[okc], np.log10(ctl["V_q25"][okc]), np.log10(ctl["V_q75"][okc]),
                    color=CONTROL, alpha=0.45, lw=0)
    ax.plot(x_all[okc], np.log10(ctl["V_med"][okc]), color=CONTROL, lw=1.2, ls="--")

    # Referencia H = 0.5 anclada en la primera escala válida
    valid = vt["valid"].to_numpy()
    if valid.any():
        i0 = int(np.flatnonzero(valid)[0])
        xr = np.array([x_all.min() - 0.05, x_all.max() + 0.05])
        ax.plot(xr, np.log10(V[i0]) - (xr - x_all[i0]), color=REF, lw=1.3, ls=(0, (5, 2, 1, 2)))

    ax.plot(x_all[pos], np.log10(V[pos]), color=col, lw=0.8, alpha=0.5, zorder=3)

    fit = est["fit"]
    in_fit = np.zeros(len(vt), bool)
    if fit is not None:
        in_fit[fit["i0"]: fit["i1"] + 1] = True
        xs = x_all[fit["i0"]: fit["i1"] + 1]
        stable = est["status"] == "estimado"
        ax.axvspan(xs.min() - 0.04, xs.max() + 0.04, color=col, alpha=0.08 if stable else 0.04, lw=0)
        xx = np.array([xs.min() - 0.08, xs.max() + 0.08])
        ax.plot(xx, fit["intercept"] + fit["beta"] * xx, color=col, lw=2.0 if stable else 1.2,
                ls="-" if stable else ":", zorder=4)

    m_in = in_fit & valid
    m_out = ~in_fit & valid & pos
    m_exc = ~valid & pos
    ax.scatter(x_all[m_in], np.log10(V[m_in]), s=46, color=col, edgecolor="white", lw=0.8, zorder=5)
    ax.scatter(x_all[m_out], np.log10(V[m_out]), s=40, facecolor="white", edgecolor=col, lw=1.3, zorder=5)
    ax.scatter(x_all[m_exc], np.log10(V[m_exc]), s=40, marker="x", color=CONTROL, lw=1.3, zorder=5)

    # Caja de resultados
    lines = []
    if fit is not None and est["status"] == "estimado":
        lines += [f"Tramo {fit['s_lo']:g}–{fit['s_hi']:g} s  (m = {fit['m_lo']}–{fit['m_hi']}, "
                  f"{fit['n_scales']} escalas)",
                  f"β̂ = {fit['beta']:.3f} ± {fit['beta_se']:.3f} (EE)",
                  f"Ĥ = {fit['H']:.3f}    R² = {fit['r2']:.4f}    RMSE = {fit['rmse_dex']:.3f} dex"]
        if np.isfinite(est["sens_max_abs_dH"]):
            lines.append(f"Sensibilidad: sin m={fit['m_lo']} → {est['sens_drop_first_H']:.3f}; "
                         f"sin m={fit['m_hi']} → {est['sens_drop_last_H']:.3f}")
        Hp = ctl["H_perm"]
        if np.isfinite(Hp).any():
            lines.append(f"Control: Ĥ med = {np.nanmedian(Hp):.3f}  [{np.nanmin(Hp):.3f}, {np.nanmax(Hp):.3f}]")
    else:
        lines += ["Ĥ sin sustento en esta serie", _wrap(est["reason"], 46)]
        lr = ctl["log10_ratio"][valid]
        if lr.size:
            lines.append(f"log10 V/V_perm (mayor escala válida) = {lr[-1]:+.2f}")
    exc = vt[~vt["valid"]]
    if len(exc):
        lines.append("Excluidas: " + ", ".join(f"m={r.m} ({r.excluded_reason})" for r in exc.itertuples()))
    ax.text(0.03, 0.03, "\n".join(lines), transform=ax.transAxes, fontsize=7.4, va="bottom", ha="left",
            color=INK, linespacing=1.35, zorder=6,
            bbox=dict(boxstyle="round,pad=0.45", fc="white", ec="#D0D0D0", lw=0.8, alpha=0.93))

    ax.set_xlabel("log10(mΔ / s)")
    ax.set_ylabel("log10 V(m)   [bytes² por intervalo Δ]")
    ax.set_title(_series_label(s), loc="left")

    # Eje superior con m (misma escala, solo etiquetas)
    sec = ax.secondary_xaxis("top", functions=(lambda x: x - np.log10(delta), lambda u: u + np.log10(delta)))
    sec.xaxis.set_major_locator(FixedLocator(np.log10(vt["m"].to_numpy())))
    sec.xaxis.set_minor_formatter(NullFormatter())
    sec.set_xticklabels([str(m) for m in vt["m"]])
    sec.tick_params(labelsize=7, colors=MUTED)
    sec.set_xlabel("m", fontsize=8, color=MUTED, labelpad=2)


def _wrap(txt: str, width: int) -> str:
    import textwrap
    return "\n".join(textwrap.wrap(txt, width))


# ==========================================================================
# 3) Robustez: repeticiones × Δ en escalas físicas comunes
# ==========================================================================
def plot_robust_variance(scen: str, recs: List[dict], cfg):
    """recs: dicts con rep, delta, series, vt, ctl. Fila 1: log10 Var(tasa)
    vs log10(mΔ); fila 2: pendiente local entre escalas vecinas."""
    series = list(dict.fromkeys(r["series"] for r in recs))
    fig, axes = plt.subplots(2, len(series), figsize=(max(4.6 * len(series) + 0.6, 9.0), 7.2), squeeze=False,
                             sharex=True, gridspec_kw={"height_ratios": [1.5, 1]}, constrained_layout=True)
    common_lo = max(min(r["vt"]["scale_s"]) for r in recs)
    common_hi = min(max(r["vt"].loc[r["vt"]["valid"], "scale_s"]) for r in recs
                    if r["vt"]["valid"].any()) if recs else 0
    for j, s in enumerate(series):
        ax, axs = axes[0, j], axes[1, j]
        for r in [r for r in recs if r["series"] == s]:
            vt = r["vt"]
            v = vt[vt["valid"]]
            if v.empty:
                continue
            st = DELTA_STYLE[round(r["delta"], 2)]
            col = REP_COLORS.get(r["rep"], INK)
            x, y = np.log10(v["scale_s"].to_numpy()), np.log10(v["V_rate"].to_numpy())
            ax.plot(x, y, color=col, ls=st["ls"], marker=st["marker"], ms=6 if st["mfc"] is None else 9,
                    mfc=col if st["mfc"] is None else "none", mec=col, lw=1.2, mew=1.2)
            if round(r["delta"], 2) == round(cfg.base_delta_s, 2):
                ok = vt["valid"].to_numpy()
                ax.plot(np.log10(vt["scale_s"][ok]), np.log10(r["ctl"]["V_med"][ok] / r["delta"] ** 2),
                        color=col, lw=0.9, ls=":", alpha=0.9)
            if len(x) >= 2:
                xm = (x[:-1] + x[1:]) / 2
                axs.plot(xm, np.diff(y) / np.diff(x), color=col, ls=st["ls"], marker=st["marker"],
                         ms=5 if st["mfc"] is None else 8, mfc=col if st["mfc"] is None else "none",
                         mec=col, lw=1.1, mew=1.1)
        for a in (ax, axs):
            a.axvspan(np.log10(common_lo) - 0.03, np.log10(common_hi) + 0.03, color="#F2F2F2", zorder=0, lw=0)
        axs.axhline(-1, color=REF, lw=1.3, ls=(0, (5, 2, 1, 2)))
        axs.axhline(0, color=MUTED, lw=0.8, ls=":")
        axs.set_ylim(-2.25, 0.35)
        axs.text(0.01, -0.97, "pendiente −1 → H = 0.5", transform=axs.get_yaxis_transform(), color=REF,
                 fontsize=7.5, va="bottom", ha="left")
        axs.text(0.99, 0.03, "pendiente 0 → H = 1", transform=axs.get_yaxis_transform(), color=MUTED,
                 fontsize=7.5, va="bottom", ha="right")
        ax.set_title(_series_label(s), loc="left")
        ax.set_ylabel("log10 Var(tasa)   [(bytes/s)²]")
        axs.set_ylabel("pendiente local β(m)")
        axs.set_xlabel("log10(mΔ / s)   — escala física")

    handles = []
    for rep, col in REP_COLORS.items():
        if any(r["rep"] == rep for r in recs):
            handles.append(Line2D([], [], color=col, lw=2, label=rep))
    handles += [
        Line2D([], [], color=INK, ls="-", marker="o", ms=6, label=f"Δ = {cfg.base_delta_s} s"),
        Line2D([], [], color=INK, ls="--", marker="s", mfc="none", ms=8, label=f"Δ = {cfg.robust_delta_s} s"),
        Line2D([], [], color=INK, ls=":", label=f"mediana del control (Δ = {cfg.base_delta_s} s)"),
        Line2D([], [], color=REF, ls=(0, (5, 2, 1, 2)), label="pendiente −1 (H = 0.5)"),
        Patch(fc="#F2F2F2", label="rango físico común de escalas válidas"),
    ]
    fig.legend(handles=handles, loc="lower center", ncol=4, bbox_to_anchor=(0.5, -0.07))
    fig.suptitle(f"{scen} — robustez entre repeticiones y resoluciones base (solo escalas válidas)",
                 x=0.0, ha="left", fontsize=12, fontweight="bold")
    return fig


# ==========================================================================
# 4) Resumen de Ĥ frente al control
# ==========================================================================
def plot_h_summary(summary, cfg):
    df = summary.copy()
    order_s = {"A+B": 0, "A": 1, "B": 2}
    df["_o"] = df["series"].map(order_s)
    df = df.sort_values(["scenario", "_o", "rep", "delta_s"]).reset_index(drop=True)

    ys, labels, y, prev = [], [], 0.0, None
    for r in df.itertuples():
        grp = (r.scenario, r.series)
        if prev is not None and grp != prev:
            y += 0.7
        ys.append(y)
        labels.append(f"{r.scenario} · {r.series} · {r.rep} · Δ = {r.delta_s:.2f} s")
        prev = grp
        y += 1
    ys = np.array(ys)

    fig, ax = plt.subplots(figsize=(8.6, 0.34 * len(df) + 1.9), constrained_layout=True)
    for yi, r in zip(ys, df.itertuples()):
        col = SERIES_COLORS[r.series]
        if np.isfinite(r.perm_H_min):
            ax.hlines(yi, r.perm_H_min, r.perm_H_max, color=CONTROL, lw=6, alpha=0.45)
            ax.plot(r.perm_H_median, yi, marker="|", color="#555555", ms=12, mew=1.6)
        if r.status == "estimado":
            sens = [v for v in (r.H, r.sens_drop_first_H, r.sens_drop_last_H) if np.isfinite(v)]
            ax.hlines(yi, min(sens), max(sens), color=col, lw=1.6)
            mk = "o" if abs(r.delta_s - cfg.base_delta_s) < 1e-9 else "s"
            ax.plot(r.H, yi, marker=mk, ms=7.5, color=col, mec="white", mew=0.8, zorder=5)
        else:
            ax.text(0.02, yi, "sin sustento", va="center", fontsize=7.5, color=MUTED, style="italic")
    ax.axvline(0.5, color=REF, lw=1.3, ls=(0, (5, 2, 1, 2)))
    ax.axvline(1.0, color=MUTED, lw=0.8, ls=":")
    ax.set_yticks(ys)
    ax.set_yticklabels(labels, fontsize=7.8)
    ax.invert_yaxis()
    ax.set_xlim(0, 1.1)
    ax.set_xlabel("Ĥ  (varianza agregada)")
    ax.grid(axis="y", visible=False)
    ax.tick_params(axis="y", length=0)
    handles = [Line2D([], [], ls="none", marker="o", color=c, ms=7, label=f"Ĥ serie {s}")
               for s, c in SERIES_COLORS.items() if s in set(df["series"])]
    handles += [
        Line2D([], [], ls="none", marker="o", color=INK, ms=6, label=f"Δ = {cfg.base_delta_s} s"),
        Line2D([], [], ls="none", marker="s", color=INK, ms=6, label=f"Δ = {cfg.robust_delta_s} s"),
        Line2D([], [], color=INK, lw=1.6, label="sensibilidad (retirar escala extrema)"),
        Patch(fc=CONTROL, alpha=0.45, label=f"control: rango de {cfg.n_perm} permutaciones"),
        Line2D([], [], ls="none", marker="|", color="#555555", ms=11, mew=1.6, label="control: mediana"),
        Line2D([], [], color=REF, ls=(0, (5, 2, 1, 2)), label="H = 0.5"),
    ]
    ax.legend(handles=handles, loc="upper center", bbox_to_anchor=(0.5, -0.07 - 0.6 / len(df)), ncol=3)
    ax.set_title("Ĥ por corrida, serie y resolución frente al control permutado", loc="left",
                 fontsize=12)
    return fig


# ==========================================================================
# 5) Periodicidad: periodograma de Welch frente al control permutado
# ==========================================================================
def plot_periodogram(run: str, scen: str, rep: str, delta: float, spec: Dict[str, dict], cfg):
    names = list(spec)
    fig, axes = plt.subplots(1, len(names), figsize=(max(4.6 * len(names) + 0.6, 7.4), 4.4),
                             squeeze=False, constrained_layout=True)
    for ax, s in zip(axes[0], names):
        f, p, ctrl, pk = spec[s]["f"], spec[s]["p"], spec[s]["ctrl"], spec[s]["peak"]
        col = SERIES_COLORS[s]
        ax.fill_between(f, ctrl["min"], ctrl["max"], color=CONTROL, alpha=0.25, lw=0)
        ax.plot(f, ctrl["med"], color=CONTROL, lw=1.1, ls="--")
        ax.plot(f, p, color=col, lw=0.9)
        ax.set_xscale("log")
        ax.set_yscale("log")
        if np.isfinite(pk["freq_Hz"]):
            j = int(np.argmin(np.abs(f - pk["freq_Hz"])))
            ax.plot(f[j], p[j], marker="v", color=INK, ms=7, zorder=5)
            txt = (f"Pico: {pk['freq_Hz']:.3g} Hz (periodo {pk['period_s']:.3g} s)\n"
                   f"prominencia {pk['prominence_dec']:.2f} déc · {pk['above_ctrl_dec']:+.2f} déc sobre el control")
        else:
            txt = "Sin picos que superen al control:\nno hay periodicidad detectable"
        ax.text(0.03, 0.03, txt, transform=ax.transAxes, fontsize=7.6, va="bottom", color=INK,
                bbox=dict(boxstyle="round,pad=0.4", fc="white", ec="#D0D0D0", lw=0.8, alpha=0.93))
        ax.set_xlabel("frecuencia (Hz)")
        ax.set_ylabel("densidad espectral  [bytes²/Hz]")
        ax.set_title(_series_label(s), loc="left")
    handles = [Line2D([], [], color=INK, lw=1, label="periodograma de la serie (Welch, 2048 intervalos)"),
               Line2D([], [], color=CONTROL, lw=1.1, ls="--", label=f"mediana de {cfg.n_perm} permutaciones"),
               Patch(fc=CONTROL, alpha=0.25, label="control: mín–máx"),
               Line2D([], [], ls="none", marker="v", color=INK, label="pico dominante")]
    fig.legend(handles=handles, loc="lower center", ncol=2 if len(names) == 1 else 4,
               bbox_to_anchor=(0.5, -0.16 if len(names) == 1 else -0.1))
    fig.suptitle(f"{scen} · {rep} — periodicidad: periodograma frente al control  ·  Δ = {delta} s, "
                 f"Nyquist = {0.5 / delta:g} Hz", x=0.0, ha="left", fontsize=12, fontweight="bold")
    return fig
