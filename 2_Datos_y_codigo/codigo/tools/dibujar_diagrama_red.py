#!/usr/bin/env python3
"""Dibuja el diagrama de la red del laboratorio (docs/diagrama_red.png y .pdf).

    python tools/dibujar_diagrama_red.py --if-c enp3s0 --if-a eno1 --if-b eno1

Las interfaces son opcionales: escriban las reales del laboratorio para que el
diagrama del entregable 1 quede completo.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
from matplotlib.patches import FancyArrowPatch, FancyBboxPatch  # noqa: E402

INK, MUTED, EDGE, ACCENT = "#222222", "#5F5F5F", "#9A9A9A", "#0072B2"


def box(ax, x, y, w, h, title, lines, accent=False, tint=False):
    fc = "#E6F0F8" if accent else ("#F2F2F2" if tint else "white")
    ax.add_patch(FancyBboxPatch((x, y), w, h, boxstyle="round,pad=0,rounding_size=8",
                                fc=fc, ec=ACCENT if accent else EDGE, lw=2 if accent else 1.2))
    if not lines:
        ax.text(x + w / 2, y + h / 2, title, fontsize=11.5, fontweight="bold", color=INK, ha="center", va="center")
        return
    ax.text(x + 14, y + h - 24, title, fontsize=11.5, fontweight="bold", color=INK, va="baseline")
    for i, ln in enumerate(lines):
        ax.text(x + 14, y + h - 46 - 19 * i, ln, fontsize=9.5, color=INK if accent else MUTED, va="baseline")


def arrow(ax, pts):
    for (x0, y0), (x1, y1) in zip(pts[:-2], pts[1:-1]):
        ax.plot([x0, x1], [y0, y1], color=EDGE, lw=1.3)
    ax.add_patch(FancyArrowPatch(pts[-2], pts[-1], arrowstyle="-|>", mutation_scale=14, color=EDGE, lw=1.3,
                                 shrinkA=0, shrinkB=0))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--if-a", default="<interfaz>")
    ap.add_argument("--if-b", default="<interfaz>")
    ap.add_argument("--if-c", default="<interfaz>")
    ap.add_argument("--switch", default="Switch", help='p. ej. "Bridge (switch virtual)"')
    ap.add_argument("--titulo", default="LAN del laboratorio: A y B envían UDP a C a través del switch; C recibe y captura")
    ap.add_argument("--out", type=Path, default=Path(__file__).resolve().parents[1] / "docs")
    a = ap.parse_args()

    fig, ax = plt.subplots(figsize=(10, 4.3))
    ax.set_xlim(0, 1000)
    ax.set_ylim(0, 430)
    ax.axis("off")
    ax.text(10, 405, a.titulo,
            fontsize=13.5, fontweight="bold", color=INK)
    ax.text(10, 382, "Red 192.168.50.0/24 · filtro de captura: udp and dst host 192.168.50.13 and "
                     "(dst port 5201 or dst port 5202)", fontsize=9.5, color=MUTED)

    box(ax, 10, 230, 285, 100, "Nodo A · cliente iperf3",
        ["IP 192.168.50.11/24", f"interfaz: {a.if_a}", "UDP → C:5201 (E1 y E2)"])
    box(ax, 10, 40, 285, 100, "Nodo B · cliente iperf3",
        ["IP 192.168.50.12/24", f"interfaz: {a.if_b}", "UDP → C:5202 (solo E2)"])
    box(ax, 390, 155, 150, 60, a.switch, [], tint=True)
    box(ax, 612, 112, 383, 148, "Nodo C · servidor y captura",
        ["IP 192.168.50.13/24", f"interfaz: {a.if_c}", "iperf3 -s -p 5201  y  -p 5202",
         f"tcpdump -i {a.if_c.split()[0]} -s 128 -w E*_R*.pcap", "punto de captura: interfaz de C"], accent=True)

    arrow(ax, [(295, 280), (348, 280), (348, 195), (390, 195)])
    arrow(ax, [(295, 90), (348, 90), (348, 175), (390, 175)])
    arrow(ax, [(540, 185), (612, 185)])
    ax.text(576, 195, "UDP", ha="center", fontsize=9.5, color=MUTED)

    a.out.mkdir(parents=True, exist_ok=True)
    for ext in ("png", "pdf"):
        fig.savefig(a.out / f"diagrama_red.{ext}", dpi=300, bbox_inches="tight", facecolor="white")
    (a.out / "diagrama_red.json").write_text(json.dumps({"if_a": a.if_a, "if_b": a.if_b, "if_c": a.if_c}),
                                             encoding="utf-8")
    print(f"Diagrama guardado en {a.out}")


if __name__ == "__main__":
    main()
