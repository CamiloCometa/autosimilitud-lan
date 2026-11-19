"""
Lectura de los CSV exportados con TShark y de los archivos auxiliares
(ventanas, cronogramas y metadatos de la corrida).

Decisión clave de precisión
---------------------------
`frame.time_epoch` se lee como TEXTO y se convierte a nanosegundos enteros
(int64). Un float64 con epoch ~1.7e9 s solo resuelve ~0.24 µs y, sobre todo,
la división (t - t0)/Δ en coma flotante puede mandar un paquete que cae
exactamente en un borde al intervalo equivocado. Con enteros, la asignación
a intervalos semiabiertos [t0 + kΔ, t0 + (k+1)Δ) es exacta.
"""
from __future__ import annotations

import logging
import re
from pathlib import Path
from typing import Dict, Optional, Tuple

import numpy as np
import pandas as pd

log = logging.getLogger(__name__)

NS = 1_000_000_000
TSHARK_COLS = ["frame.time_epoch", "frame.len", "ip.src", "udp.dstport"]
_RUN_RE = re.compile(r"(E\d+)[ _\-]*R(\d+)", re.IGNORECASE)


# --------------------------------------------------------------------------
# Utilidades de tiempo
# --------------------------------------------------------------------------
def epoch_str_to_ns(values: pd.Series) -> np.ndarray:
    """'1763500000.123456789' -> 1763500000123456789 (int64, exacto)."""
    s = values.astype(str).str.strip()
    parts = s.str.split(".", n=1, expand=True)
    sec = parts[0].astype(np.int64)
    if parts.shape[1] > 1:
        frac = parts[1].fillna("0").str.ljust(9, "0").str[:9].astype(np.int64)
    else:
        frac = 0
    return (sec * NS + frac).to_numpy(dtype=np.int64)


def time_value_to_ns(value) -> int:
    """Acepta epoch (texto o número) o fecha ISO-8601 con zona horaria."""
    txt = str(value).strip()
    if re.fullmatch(r"\d+(\.\d+)?", txt):
        return int(epoch_str_to_ns(pd.Series([txt]))[0])
    ts = pd.Timestamp(txt)
    if ts.tzinfo is None:
        raise ValueError(f"La fecha '{txt}' no tiene zona horaria; use epoch o ISO con offset.")
    return int(ts.value)


# --------------------------------------------------------------------------
# Identificación de la corrida
# --------------------------------------------------------------------------
def parse_run_name(path: Path) -> Tuple[str, str, str]:
    """E1_R2.csv -> ('E1_R2', 'E1', 'R2'). Falla si el nombre no lo permite."""
    m = _RUN_RE.search(path.stem)
    if not m:
        raise ValueError(
            f"No se reconoce escenario/repetición en '{path.name}'. "
            "Use nombres como E1_R1.csv, E2_R2.csv."
        )
    scen, rep = m.group(1).upper(), f"R{m.group(2)}"
    return f"{scen}_{rep}", scen, rep


# --------------------------------------------------------------------------
# Traza
# --------------------------------------------------------------------------
def read_trace(path: Path) -> pd.DataFrame:
    """Lee un CSV de TShark y devuelve columnas normalizadas:
    t_ns (int64), length (int64), src (str), dport (Int64).
    Las filas incompletas o con campos múltiples se descartan con aviso."""
    df = pd.read_csv(
        path,
        dtype={c: str for c in TSHARK_COLS},
        usecols=lambda c: c.strip() in TSHARK_COLS,
        on_bad_lines="warn",
        skipinitialspace=True,
    )
    df.columns = [c.strip() for c in df.columns]
    missing = set(TSHARK_COLS) - set(df.columns)
    if missing:
        raise ValueError(f"{path.name}: faltan columnas {sorted(missing)}")

    n0 = len(df)
    df = df.dropna(subset=TSHARK_COLS)
    # Campos con múltiples valores (p. ej. túneles) no son esperables aquí.
    ok = df["udp.dstport"].str.fullmatch(r"\d+") & df["frame.len"].str.fullmatch(r"\d+")
    df = df[ok]
    if len(df) < n0:
        log.warning("%s: %d filas descartadas por campos vacíos o inválidos", path.name, n0 - len(df))

    out = pd.DataFrame(
        {
            "t_ns": epoch_str_to_ns(df["frame.time_epoch"]),
            "length": df["frame.len"].astype(np.int64).to_numpy(),
            "src": df["ip.src"].str.strip().to_numpy(),
            "dport": df["udp.dstport"].astype(np.int64).to_numpy(),
        }
    )
    if not out["t_ns"].is_monotonic_increasing:
        log.warning("%s: marcas de tiempo no monótonas; se ordenan.", path.name)
        out = out.sort_values("t_ns", kind="mergesort").reset_index(drop=True)
    return out


# --------------------------------------------------------------------------
# Archivos auxiliares (todos opcionales)
# --------------------------------------------------------------------------
def read_windows(path: Optional[Path]) -> Dict[str, dict]:
    """CSV con columnas: run, t0 [, duration_s].
    t0 en epoch (recomendado, reloj de C) o ISO-8601 con zona horaria."""
    if path is None:
        return {}
    df = pd.read_csv(path, dtype=str, comment="#")
    df.columns = [c.strip() for c in df.columns]
    res = {}
    for _, r in df.iterrows():
        res[r["run"].strip().upper()] = {
            "t0_ns": time_value_to_ns(r["t0"]),
            "duration_s": float(r["duration_s"]) if "duration_s" in df and pd.notna(r.get("duration_s")) else None,
        }
    return res


def read_schedule(path: Optional[Path]) -> pd.DataFrame:
    """Cronograma declarado: run, source (A/B), start_s, end_s (segundos desde t0)."""
    cols = ["run", "source", "start_s", "end_s"]
    if path is None:
        return pd.DataFrame(columns=cols)
    df = pd.read_csv(path, comment="#")
    df.columns = [c.strip() for c in df.columns]
    df["run"] = df["run"].str.strip().str.upper()
    df["source"] = df["source"].str.strip().str.upper()
    return df[cols]


def read_metadata(path: Optional[Path]) -> pd.DataFrame:
    """Metadatos libres por corrida (run + columnas como udp_loss_pct,
    capture_drops, notas). Se anexan tal cual a la tabla resumen."""
    if path is None:
        return pd.DataFrame(columns=["run"])
    df = pd.read_csv(path, dtype=str, comment="#")
    df.columns = [c.strip() for c in df.columns]
    df["run"] = df["run"].str.strip().str.upper()
    return df
