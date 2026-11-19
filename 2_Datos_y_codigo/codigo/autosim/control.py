"""
Control por permutación.

Permutar los intervalos X_k conserva exactamente la distribución de bytes por
intervalo (y por tanto V(1)) pero destruye el orden temporal. Para una serie
sin dependencia, V(m) ≈ V(1)/m (pendiente -1, H = 0.5). Cada permutación se
evalúa en el MISMO tramo de escalas que la serie original.

Semillas: cada serie recibe una semilla derivada de forma determinista de la
semilla base y de su identificador (corrida|serie|Δ) mediante
numpy.random.SeedSequence. Así cada resultado es reproducible por separado y
no depende del orden en que se procesen los archivos.
"""
from __future__ import annotations

import zlib
from typing import Optional

import numpy as np
import pandas as pd

from .hurst import slope_on
from .series import block_means


def derived_seed(base_seed: int, key: str) -> int:
    ss = np.random.SeedSequence([base_seed, zlib.crc32(key.encode("utf-8"))])
    return int(ss.generate_state(1, dtype=np.uint32)[0])


def permutation_control(X: np.ndarray, vt: pd.DataFrame, fit: Optional[dict],
                        n_perm: int, seed: int) -> dict:
    rng = np.random.default_rng(seed)
    scales = vt["m"].to_numpy()
    scale_s = vt["scale_s"].to_numpy()
    Vp = np.empty((n_perm, scales.size))
    for p in range(n_perm):
        Xp = rng.permutation(X)
        for j, m in enumerate(scales):
            Y = block_means(Xp, m)
            Vp[p, j] = np.var(Y, ddof=1) if Y.size >= 2 else np.nan

    H = np.full(n_perm, np.nan)
    if fit is not None:
        idx = np.arange(fit["i0"], fit["i1"] + 1)
        H = np.array([1 + slope_on(Vp[p], scale_s, idx) / 2 for p in range(n_perm)])

    with np.errstate(divide="ignore", invalid="ignore"):
        logratio = np.log10(vt["V"].to_numpy() / np.median(Vp, axis=0))
    return {
        "seed": seed,
        "V_perm": Vp,
        "V_med": np.median(Vp, axis=0),
        "V_min": Vp.min(axis=0), "V_max": Vp.max(axis=0),
        "V_q25": np.quantile(Vp, 0.25, axis=0), "V_q75": np.quantile(Vp, 0.75, axis=0),
        "H_perm": H,
        "log10_ratio": logratio,          # log10 V_orig / mediana V_perm por escala
    }


def control_verdict(H_hat: float, H_perm: np.ndarray) -> str:
    """Comparación descriptiva de Ĥ frente al rango (mín–máx) del control."""
    if not np.isfinite(H_hat) or not np.isfinite(H_perm).any():
        return "sin Ĥ: comparar curvas"
    lo, hi = np.nanmin(H_perm), np.nanmax(H_perm)
    if H_hat > hi:
        return "Ĥ por encima del rango del control"
    if H_hat < lo:
        return "Ĥ por debajo del rango del control"
    return "Ĥ dentro del rango del control"
