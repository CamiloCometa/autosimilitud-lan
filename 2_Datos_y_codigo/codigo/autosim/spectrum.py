"""
Periodicidad: periodograma de Welch de X_k frente al de sus permutaciones.

La guía pide revisar "tendencias, cambios de nivel, periodicidad y coincidencia
con el cronograma". Un ciclo regular (p. ej. el ritmo de envío de iperf3 o una
pausa programada repetida) aparece como un pico estrecho en la densidad
espectral; la permutación lo destruye, así que el control da la referencia
plana. Se reporta el pico más prominente (en décadas de log10 PSD) y su
periodo. Exceso de potencia a bajas frecuencias SIN pico = variabilidad lenta
(ráfagas largas, deriva), no periodicidad.
"""
from __future__ import annotations

import numpy as np
from scipy import signal


def welch_psd(X: np.ndarray, delta_s: float, nperseg: int = 2048):
    f, p = signal.welch(X, fs=1.0 / delta_s, nperseg=min(nperseg, X.size), detrend="constant")
    return f[1:], p[1:]                                   # sin la frecuencia 0


def periodogram_control(X: np.ndarray, delta_s: float, n_perm: int, seed: int):
    rng = np.random.default_rng(seed)
    f, p = welch_psd(X, delta_s)
    P = np.array([welch_psd(rng.permutation(X), delta_s)[1] for _ in range(n_perm)])
    ctrl = {"med": np.median(P, axis=0), "min": P.min(axis=0), "max": P.max(axis=0)}
    peak = dominant_peak(f, p, ctrl["max"])
    return f, p, ctrl, peak


def dominant_peak(f: np.ndarray, p: np.ndarray, ctrl_max: np.ndarray, min_prom_dec: float = 0.3) -> dict:
    """Pico más prominente de log10 PSD que además supera el máximo del control."""
    good = p > 0
    if good.sum() < 5:
        return {"freq_Hz": np.nan, "period_s": np.nan, "prominence_dec": np.nan, "above_ctrl_dec": np.nan}
    lp = np.log10(np.where(good, p, np.nan))
    lp = np.nan_to_num(lp, nan=np.nanmin(lp))
    idx, props = signal.find_peaks(lp, prominence=min_prom_dec)
    if idx.size:
        above = lp[idx] - np.log10(np.maximum(ctrl_max[idx], 1e-300))
        keep = above > 0
        idx, prom, above = idx[keep], props["prominences"][keep], above[keep]
    if not idx.size:
        return {"freq_Hz": np.nan, "period_s": np.nan, "prominence_dec": np.nan, "above_ctrl_dec": np.nan}
    k = int(np.argmax(prom))
    fk = float(f[idx[k]])
    return {"freq_Hz": fk, "period_s": 1.0 / fk, "prominence_dec": float(prom[k]),
            "above_ctrl_dec": float(above[k])}
