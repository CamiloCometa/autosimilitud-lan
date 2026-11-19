"""
De la traza a la serie regular X_k y a sus versiones agregadas.

    X_k = Σ L_i   para  t0 + kΔ ≤ t_i < t0 + (k+1)Δ ,   k = 0..N-1,  N = T/Δ

Los intervalos vacíos se conservan con 0 (incluidos los extremos de la
ventana). Todo el cálculo de índices se hace con enteros (ns).
"""
from __future__ import annotations

import logging
from typing import Dict, Optional, Tuple

import numpy as np
import pandas as pd

from .config import SCENARIO_SERIES, SERVER_IP, SOURCES
from .trace_io import NS

log = logging.getLogger(__name__)


# --------------------------------------------------------------------------
# Selección de flujos
# --------------------------------------------------------------------------
def flow_masks(df: pd.DataFrame, scenario: str) -> Tuple[Dict[str, np.ndarray], int]:
    """Máscaras booleanas por serie y número de paquetes no asignados
    (origen/puerto inesperado). E2: 'A+B' = A ∪ B con el mismo t0."""
    base = {
        name: (df["src"].to_numpy() == ip) & (df["dport"].to_numpy() == port)
        for name, (ip, port) in SOURCES.items()
    }
    wanted = SCENARIO_SERIES[scenario]
    masks: Dict[str, np.ndarray] = {}
    for s in wanted:
        if s == "A+B":
            masks[s] = base["A"] | base["B"]
        else:
            masks[s] = base[s]
    used = np.zeros(len(df), dtype=bool)
    for s in wanted:
        used |= masks[s]
    return masks, int((~used).sum())


def determine_t0(df: pd.DataFrame, masks: Dict[str, np.ndarray], scenario: str,
                 run: str, windows: Dict[str, dict]) -> Tuple[int, str]:
    """Origen temporal de la ventana.
    1) Si la corrida figura en el archivo de ventanas, se usa ese t0 (reloj de C).
    2) E1: primer datagrama recibido de la serie principal (criterio del taller).
    3) E2 sin ventana registrada: primer datagrama de A∪B, con advertencia,
       porque el taller pide fijar t0 ANTES de las ráfagas."""
    if run in windows:
        return windows[run]["t0_ns"], "archivo de ventanas"
    main = SCENARIO_SERIES[scenario][0]
    t = df["t_ns"].to_numpy()[masks[main]]
    if t.size == 0:
        raise ValueError(f"{run}: la serie principal {main} no tiene paquetes.")
    if scenario == "E2":
        log.warning("%s: sin t0 registrado; se usa el primer datagrama (el taller pide "
                    "fijarlo antes de las ráfagas: añada --windows).", run)
        return int(t.min()), "primer datagrama (sin ventana registrada)"
    return int(t.min()), "primer datagrama recibido"


# --------------------------------------------------------------------------
# Serie regular
# --------------------------------------------------------------------------
def n_intervals(window_s: float, delta_s: float) -> int:
    n = window_s / delta_s
    if abs(n - round(n)) > 1e-9:
        raise ValueError(f"La ventana {window_s} s no es múltiplo de Δ={delta_s} s")
    return int(round(n))


def bin_bytes(t_ns: np.ndarray, length: np.ndarray, t0_ns: int,
              delta_s: float, window_s: float) -> Tuple[np.ndarray, dict]:
    """Bytes de trama por intervalo semiabierto. Devuelve X (float64, len N)
    y un diccionario con conteos de control."""
    N = n_intervals(window_s, delta_s)
    d_ns = int(round(delta_s * NS))
    rel = t_ns - np.int64(t0_ns)
    idx = rel // d_ns                                   # floor exacto en enteros
    inside = (idx >= 0) & (idx < N)
    X = np.bincount(idx[inside].astype(np.int64), weights=length[inside].astype(np.float64),
                    minlength=N).astype(np.float64)
    info = {
        "N": N,
        "packets_in": int(inside.sum()),
        "packets_before": int((idx < 0).sum()),
        "packets_after": int((idx >= N).sum()),
        "bytes_in": float(length[inside].sum()),
        "first_rel_s": float(rel[inside].min() / NS) if inside.any() else np.nan,
        "last_rel_s": float(rel[inside].max() / NS) if inside.any() else np.nan,
    }
    return X, info


def block_means(X: np.ndarray, m: int) -> np.ndarray:
    """Y_j^(m): medias de M_m = ⌊N/m⌋ bloques completos no solapados.
    La cola incompleta (N mod m intervalos) se descarta."""
    M = X.size // m
    return X[: M * m].reshape(M, m).mean(axis=1)


def rate_series(X: np.ndarray, delta_s: float, m: int) -> Tuple[np.ndarray, np.ndarray]:
    """Tasa en bytes/s por bloque (bytes del bloque / duración mΔ) y
    tiempos de inicio de bloque relativos a t0."""
    Y = block_means(X, m)
    t = np.arange(Y.size) * m * delta_s
    return t, Y / delta_s


# --------------------------------------------------------------------------
# Diagnósticos de la serie (artefactos visibles en la traza)
# --------------------------------------------------------------------------
def silence_stats(X: np.ndarray, delta_s: float) -> dict:
    zero = X == 0
    longest = 0
    run = 0
    for z in zero:                      # N ≤ 12 000: un bucle simple es suficiente
        run = run + 1 if z else 0
        longest = max(longest, run)
    return {"zero_frac": float(zero.mean()), "longest_silence_s": longest * delta_s}


def trend_stats(X: np.ndarray, delta_s: float, block_s: float = 3.2) -> dict:
    """Tendencia lineal de la tasa a la resolución block_s (en % de la media
    por cada 100 s). Útil para detectar derivas o cambios de nivel."""
    from scipy import stats
    m = int(round(block_s / delta_s))
    t, r = rate_series(X, delta_s, m)
    if r.mean() == 0 or r.size < 3:
        return {"trend_pct_per_100s": np.nan, "trend_p": np.nan}
    res = stats.linregress(t, r)
    return {"trend_pct_per_100s": 100 * res.slope * 100 / r.mean(), "trend_p": res.pvalue}


def on_segments(X: np.ndarray, delta_s: float, gap_merge_s: float) -> np.ndarray:
    """Periodos activos observados: intervalos con bytes > 0, uniendo
    silencios más cortos que gap_merge_s. Devuelve array (k, 2) en s."""
    on = X > 0
    if not on.any():
        return np.empty((0, 2))
    edges = np.diff(np.r_[0, on.astype(int), 0])
    starts, ends = np.flatnonzero(edges == 1), np.flatnonzero(edges == -1)
    merged = [[starts[0], ends[0]]]
    gap = int(round(gap_merge_s / delta_s))
    for s, e in zip(starts[1:], ends[1:]):
        if s - merged[-1][1] <= gap:
            merged[-1][1] = e
        else:
            merged.append([s, e])
    return np.asarray(merged, dtype=float) * delta_s


def segments_to_mask(segs: np.ndarray, N: int, delta_s: float) -> np.ndarray:
    mask = np.zeros(N, dtype=bool)
    for a, b in np.asarray(segs).reshape(-1, 2):
        i0, i1 = int(np.floor(a / delta_s + 1e-9)), int(np.ceil(b / delta_s - 1e-9))
        mask[max(i0, 0): min(i1, N)] = True
    return mask


def activity_summary(segA: np.ndarray, segB: np.ndarray, N: int, delta_s: float,
                     declared: Optional[Dict[str, np.ndarray]] = None) -> dict:
    """Fracciones de tiempo solo-A, solo-B, ambos y silencio (E2) y, si hay
    cronograma, concordancia observado vs declarado por fuente."""
    a, b = segments_to_mask(segA, N, delta_s), segments_to_mask(segB, N, delta_s)
    out = {
        "only_A_frac": float((a & ~b).mean()),
        "only_B_frac": float((~a & b).mean()),
        "both_frac": float((a & b).mean()),
        "silence_frac": float((~a & ~b).mean()),
        "n_bursts_A": int(len(segA)),
        "n_bursts_B": int(len(segB)),
    }
    if declared:
        for src, obs in (("A", a), ("B", b)):
            if src in declared and len(declared[src]):
                dec = segments_to_mask(declared[src], N, delta_s)
                out[f"schedule_agreement_{src}"] = float((dec == obs).mean())
    return out
