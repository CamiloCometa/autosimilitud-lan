"""
Método de varianza agregada (variance–time plot).

    V(m) = Var_muestral( Y^(m) )  ∝  m^(2H-2)   ⇒   log10 V = c + β log10(mΔ),
    Ĥ = 1 + β̂/2

Selección del tramo
-------------------
1. Escalas válidas: V(m) > 0 y M_m ≥ min_blocks (se documentan las excluidas).
2. Candidatos: todos los tramos de ≥ min_fit_scales escalas válidas
   CONSECUTIVAS (en la rejilla m = 1, 2, 4, …).
3. Un tramo es "linealmente estable" si
     RMSE de los residuos (en décadas de log10 V) ≤ max_rmse_dex,
     todas las pendientes locales (entre escalas vecinas) difieren de β̂
     en menos de max_local_slope_dev   (descarta curvaturas que un R² alto
     puede esconder), y
     -2 ≤ β̂ ≤ 0   (0 ≤ Ĥ ≤ 1, rango admisible del modelo).
   R² se reporta siempre, pero NO se usa por defecto como criterio: cuando la
   curva es casi plana (β̂ ≈ 0, Ĥ ≈ 1) la varianza explicada es pequeña aunque
   los puntos estén perfectamente alineados, y R² rechazaría tramos lineales.
   Si se desea, --r2-min añade un umbral de R² adicional.
4. Se elige el tramo estable más largo; a igualdad, el de menor RMSE.
   Si no hay ninguno, la estimación queda "sin sustento" para esa serie.
Opcionalmente, el tramo se puede fijar en segundos (fit_range_s) para
comparar exactamente el mismo rango físico entre corridas y resoluciones.
"""
from __future__ import annotations

from typing import List, Optional, Sequence

import numpy as np
import pandas as pd
from scipy import stats

from .series import block_means


# --------------------------------------------------------------------------
# Curva de varianza
# --------------------------------------------------------------------------
def variance_time(X: np.ndarray, delta_s: float, scales: Sequence[int],
                  min_blocks: int) -> pd.DataFrame:
    rows = []
    scale_ref = max(float(np.mean(X)) ** 2, 1.0)
    for m in scales:
        M = X.size // m
        Y = block_means(X, m) if M > 0 else np.array([])
        V = float(np.var(Y, ddof=1)) if M >= 2 else np.nan
        if M < min_blocks:
            reason = f"M<{min_blocks}"
        elif not np.isfinite(V) or V <= 1e-12 * scale_ref:
            reason = "V=0"
        else:
            reason = ""
        rows.append({
            "m": m, "scale_s": m * delta_s, "M": M, "V": V,
            # Varianza de la TASA (bytes/s)²: comparable entre distintos Δ.
            "V_rate": V / delta_s ** 2 if np.isfinite(V) else np.nan,
            "valid": reason == "", "excluded_reason": reason,
        })
    return pd.DataFrame(rows)


# --------------------------------------------------------------------------
# Ajustes
# --------------------------------------------------------------------------
def _fit(x: np.ndarray, y: np.ndarray) -> dict:
    res = stats.linregress(x, y)
    n = x.size
    tcrit = stats.t.ppf(0.975, n - 2) if n > 2 else np.nan
    local = np.diff(y) / np.diff(x)
    beta = res.slope
    return {
        "n_scales": n,
        "beta": beta,
        "beta_se": res.stderr,
        "intercept": res.intercept,
        "r2": res.rvalue ** 2,
        "H": 1 + beta / 2,
        # IC95% indicativo: supone residuos independientes, lo que en un
        # variance–time plot no se cumple estrictamente (escalas anidadas).
        "H_ci_lo": 1 + (beta - tcrit * res.stderr) / 2,
        "H_ci_hi": 1 + (beta + tcrit * res.stderr) / 2,
        "max_local_dev": float(np.max(np.abs(local - beta))),
        "rmse_dex": float(np.sqrt(np.mean((y - (res.intercept + beta * x)) ** 2))),
    }


def slope_on(V: np.ndarray, scale_s: np.ndarray, idx: np.ndarray) -> float:
    """Pendiente OLS en log10 sobre las posiciones idx (para permutaciones)."""
    v = V[idx]
    if np.any(~np.isfinite(v)) or np.any(v <= 0):
        return np.nan
    return float(np.polyfit(np.log10(scale_s[idx]), np.log10(v), 1)[0])


def _segment_record(vt: pd.DataFrame, i0: int, i1: int, cfg) -> dict:
    sub = vt.iloc[i0: i1 + 1]
    rec = _fit(np.log10(sub["scale_s"].to_numpy()), np.log10(sub["V"].to_numpy()))
    rec.update({
        "i0": i0, "i1": i1,
        "m_lo": int(sub["m"].iloc[0]), "m_hi": int(sub["m"].iloc[-1]),
        "s_lo": float(sub["scale_s"].iloc[0]), "s_hi": float(sub["scale_s"].iloc[-1]),
    })
    rec["stable"] = bool(
        rec["rmse_dex"] <= cfg.max_rmse_dex
        and (cfg.r2_min is None or rec["r2"] >= cfg.r2_min)
        and rec["max_local_dev"] <= cfg.max_local_slope_dev
        and -2.0 <= rec["beta"] <= 0.0
    )
    return rec


def candidate_segments(vt: pd.DataFrame, cfg) -> List[dict]:
    """Todos los tramos de escalas válidas consecutivas con longitud mínima."""
    valid = vt["valid"].to_numpy()
    runs, start = [], None
    for i, v in enumerate(np.r_[valid, False]):
        if v and start is None:
            start = i
        elif not v and start is not None:
            runs.append((start, i - 1))
            start = None
    cands = []
    k = cfg.min_fit_scales
    for a, b in runs:
        for i0 in range(a, b - k + 2):
            for i1 in range(i0 + k - 1, b + 1):
                cands.append(_segment_record(vt, i0, i1, cfg))
    return cands


def estimate_hurst(vt: pd.DataFrame, cfg) -> dict:
    """Devuelve el ajuste elegido (o la razón por la que no hay sustento),
    la sensibilidad al retirar una escala extrema y todos los candidatos."""
    cands = candidate_segments(vt, cfg)
    out = {"candidates": cands, "status": "sin sustento", "reason": "", "fit": None,
           "sens_drop_first_H": np.nan, "sens_drop_last_H": np.nan, "sens_max_abs_dH": np.nan,
           "mode": "automático" if cfg.fit_range_s is None else "forzado"}

    if cfg.fit_range_s is not None:
        lo, hi = cfg.fit_range_s
        sel = np.flatnonzero((vt["scale_s"] >= lo * (1 - 1e-9)) & (vt["scale_s"] <= hi * (1 + 1e-9)))
        if sel.size < cfg.min_fit_scales:
            out["reason"] = f"el rango forzado {lo}–{hi} s tiene {sel.size} escalas (<{cfg.min_fit_scales})"
            return out
        if not vt["valid"].iloc[sel].all():
            bad = vt.iloc[sel].query("not valid")
            out["reason"] = "rango forzado incluye escalas excluidas: " + \
                ", ".join(f"m={r.m} ({r.excluded_reason})" for r in bad.itertuples())
            return out
        chosen = _segment_record(vt, int(sel[0]), int(sel[-1]), cfg)
        if not chosen["stable"]:
            out["reason"] = "rango forzado no es linealmente estable (ver R² / pendientes locales)"
            out["fit"] = chosen               # se conserva para la figura
            return out
    else:
        if not cands:
            nval = int(vt["valid"].sum())
            out["reason"] = f"solo {nval} escalas válidas consecutivas (<{cfg.min_fit_scales})"
            return out
        stable = [c for c in cands if c["stable"]]
        if not stable:
            best = min(cands, key=lambda c: c["max_local_dev"])
            r2txt = f", R²≥{cfg.r2_min}" if cfg.r2_min is not None else ""
            out["reason"] = (f"ningún tramo cumple RMSE≤{cfg.max_rmse_dex} dex, |pend. local−β|≤"
                             f"{cfg.max_local_slope_dev}{r2txt} y 0≤H≤1 (mejor: m={best['m_lo']}–"
                             f"{best['m_hi']}, desv. local {best['max_local_dev']:.2f}, "
                             f"RMSE {best['rmse_dex']:.3f})")
            return out
        chosen = max(stable, key=lambda c: (c["n_scales"], -c["rmse_dex"]))

    out.update(status="estimado", fit=chosen)

    # Sensibilidad: retirar la escala extrema inferior / superior (si quedan ≥ k)
    i0, i1 = chosen["i0"], chosen["i1"]
    if chosen["n_scales"] - 1 >= cfg.min_fit_scales:
        f1 = _segment_record(vt, i0 + 1, i1, cfg)
        f2 = _segment_record(vt, i0, i1 - 1, cfg)
        out["sens_drop_first_H"] = f1["H"]
        out["sens_drop_last_H"] = f2["H"]
        out["sens_max_abs_dH"] = max(abs(f1["H"] - chosen["H"]), abs(f2["H"] - chosen["H"]))
    return out
