#!/usr/bin/env python3
"""
Genera trazas SINTÉTICAS con el mismo formato que la exportación de TShark,
para probar el pipeline antes de tener las capturas reales.

    python tools/generate_synthetic.py --out data/example

Crea E1_R1.csv, E1_R2.csv, E2_R1.csv, E2_R2.csv y, en <out>/meta/,
windows.csv, schedule.csv y runs.csv. NO son datos del laboratorio: sirven
solo para verificar que el código corre y que las figuras se ven bien.

Modelo
------
E1: A envía datagramas de 1200 B (trama 1242 B) cada 2.4 ms (4 Mbit/s de
    carga útil), con jitter gaussiano σ = 0.15 ms y pérdida 0.05 %.
E2: A y B alternan ON/OFF con duraciones enteras uniformes en [1, 20] s,
    cronograma distinto por nodo, silencio inicial y final. En cada ON, el
    primer datagrama llega ~80 ms después del inicio declarado (arranque de
    iperf3).
"""
from __future__ import annotations

import argparse
from pathlib import Path

import numpy as np
import pandas as pd

NS = 1_000_000_000
FRAME = 1242
IPI_NS = 2_400_000                      # 1200*8 / 4e6 s
SRC = {"A": ("192.168.50.11", 5201), "B": ("192.168.50.12", 5202)}


def cbr(rng, t_start_ns: int, dur_s: float) -> np.ndarray:
    n = int(dur_s * NS // IPI_NS)
    t = t_start_ns + np.arange(n, dtype=np.int64) * IPI_NS
    t = t + rng.normal(0, 150_000, n).astype(np.int64)
    keep = rng.random(n) > 0.0005
    return np.sort(t[keep])


def schedule(rng, offset: float, T: float = 600.0, tail: float = 8.0):
    segs, t, on = [], offset, True
    while t < T - tail:
        d = int(rng.integers(1, 21))
        if on:
            end = min(t + d, T - tail)
            segs.append((t, end))
        t += d
        on = not on
    return segs


def write_csv(path: Path, t_ns: np.ndarray, src: str):
    ip, port = SRC[src]
    df = pd.DataFrame({
        "frame.time_epoch": [f"{v // NS}.{v % NS:09d}" for v in t_ns],
        "frame.len": FRAME, "ip.src": ip, "udp.dstport": port,
    })
    return df


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", type=Path, default=Path("data/example"))
    ap.add_argument("--seed", type=int, default=7)
    a = ap.parse_args()
    rng = np.random.default_rng(a.seed)
    a.out.mkdir(parents=True, exist_ok=True)
    (a.out / "meta").mkdir(exist_ok=True)

    windows, sched, runs = [], [], []
    base = 1_763_510_400 * NS                         # 2025-11-19 00:00 UTC (arbitrario)
    for r in (1, 2):
        # ---- E1
        t0 = base + r * 3_600 * NS + 123_456_789
        t = cbr(rng, t0, 600.4)
        write_csv(None, t, "A").to_csv(a.out / f"E1_R{r}.csv", index=False)
        runs.append({"run": f"E1_R{r}", "udp_loss": "0.05% (sintético)", "capture_drops": "0"})

        # ---- E2
        w0 = base + (10 + r) * 3_600 * NS + 500_000_000
        windows.append({"run": f"E2_R{r}", "t0": f"{w0 // NS}.{w0 % NS:09d}", "duration_s": 600})
        frames = []
        for src, off in (("A", rng.uniform(2, 5)), ("B", rng.uniform(4, 9))):
            for s, e in schedule(rng, off):
                sched.append({"run": f"E2_R{r}", "source": src, "start_s": round(s, 3), "end_s": round(e, 3)})
                tt = cbr(rng, w0 + int((s + 0.08) * NS), max(e - s - 0.08, 0))
                frames.append(write_csv(None, tt, src).assign(_t=tt))
        df = pd.concat(frames).sort_values("_t").drop(columns="_t")
        df.to_csv(a.out / f"E2_R{r}.csv", index=False)
        runs.append({"run": f"E2_R{r}", "udp_loss": "0.05% A / 0.05% B (sintético)", "capture_drops": "0"})

    pd.DataFrame(windows).to_csv(a.out / "meta" / "windows.csv", index=False)
    pd.DataFrame(sched).to_csv(a.out / "meta" / "schedule.csv", index=False)
    pd.DataFrame(runs).to_csv(a.out / "meta" / "runs.csv", index=False)
    print(f"Trazas sintéticas en {a.out}")


if __name__ == "__main__":
    main()
