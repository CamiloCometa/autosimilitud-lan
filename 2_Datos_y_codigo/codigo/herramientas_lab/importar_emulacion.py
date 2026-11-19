#!/usr/bin/env python3
"""
Importa al proyecto los resultados de laboratorio_emulado.py:

  data/pcap/  ← E*_R*.pcap
  data/raw/   ← E*_R*.csv (exportados con TShark, mismo filtro y campos de la guía)
  data/meta/  ← windows.csv (t0 de E2), schedule.csv (cronogramas), runs.csv (pérdidas y descartes)
  data/lab/   ← versiones, registros de comandos, pings, interfaces, ventanas.txt,
                hoja_registro.csv y los reportes JSON de iperf3

    python3 herramientas_lab/importar_emulacion.py --lab ../lab_emulado
"""
from __future__ import annotations

import argparse
import json
import shutil
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FILTER = "ip.dst == 192.168.50.13 && (udp.dstport == 5201 || udp.dstport == 5202)"
FIELDS = ("frame.time_epoch", "frame.len", "ip.src", "udp.dstport")


def fmt_loss(d: dict) -> str:
    if not d or d.get("packets") in (None, 0):
        return "sin dato"
    return f"{(d['lost_pct'] or 0):.3f}% ({d['lost']}/{d['packets']})"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--lab", type=Path, required=True)
    ap.add_argument("--project", type=Path, default=ROOT)
    a = ap.parse_args()
    P = a.project
    for d in ("data/pcap", "data/raw", "data/meta", "data/lab"):
        (P / d).mkdir(parents=True, exist_ok=True)

    runs = sorted(p.name for p in a.lab.iterdir() if p.is_dir() and (p / "resultado.json").exists())
    win_rows, sch_rows, run_rows, hoja, ventanas = [], [], [], [], []
    for run in runs:
        d = a.lab / run
        res = json.loads((d / "resultado.json").read_text())
        pcap = d / f"{run}.pcap"
        shutil.copy2(pcap, P / "data" / "pcap" / pcap.name)
        cmd = ["tshark", "-r", str(pcap), "-Y", FILTER, "-T", "fields", "-E", "header=y", "-E", "separator=,"]
        for f in FIELDS:
            cmd += ["-e", f]
        with open(P / "data" / "raw" / f"{run}.csv", "wb") as fh:
            subprocess.run(cmd, stdout=fh, stderr=subprocess.DEVNULL, check=True)

        if res.get("t0"):
            win_rows.append(f"{run},{res['t0']},600")
        for node, a_s, b_s in res.get("schedule", []):
            sch_rows.append(f"{run},{node},{a_s},{b_s}")
        loss = res["loss"]
        if run.startswith("E1"):
            ltxt = fmt_loss(loss.get("A"))
            hoja.append(f"{run},{res['t_start']},{res['t_end']},{ltxt},—,{res['drops']},t0 = primer datagrama")
        else:
            ltxt = f"A {fmt_loss(loss.get('A'))} / B {fmt_loss(loss.get('B'))}"
            hoja.append(f"{run},{res['t0']},{res['t_end']},{fmt_loss(loss.get('A'))},{fmt_loss(loss.get('B'))},"
                        f"{res['drops']},t0 fijado antes de las ráfagas")
        run_rows.append(f"{run},{ltxt},{res['drops']},red emulada (namespaces + bridge)")
        ventanas.append(f"{run}\tinicio/t0={res['t_start']}\tfin={res['t_end']}")

        # registros por corrida
        lab = P / "data" / "lab"
        shutil.copy2(d / "registro_comandos.txt", lab / f"registro_{run}.txt")
        for f in d.glob("ping_*.txt"):
            shutil.copy2(f, lab / f"{run}_{f.name}")
        info = "\n".join(f"--- nodo {n}\n" + (d / f"interfaces_{n}.txt").read_text() for n in "ABC")
        (lab / f"interfaces_{run}.txt").write_text(info, encoding="utf-8")
        shutil.copy2(d / "tcpdump_stderr.txt", lab / f"tcpdump_{run}.txt")
        with open(lab / f"iperf_{run}.jsonl", "w", encoding="utf-8") as out:
            for j in sorted(d.glob("iperf_*.json")):
                txt = j.read_text().strip()
                try:
                    out.write(json.dumps({"archivo": j.name, "reporte": json.loads(txt)}) + "\n")
                except json.JSONDecodeError:
                    out.write(json.dumps({"archivo": j.name, "texto": txt}) + "\n")

    (P / "data" / "meta" / "windows.csv").write_text(
        "# t0 de E2 con el reloj de C (anfitrión de la emulación)\nrun,t0,duration_s\n" + "\n".join(win_rows) + "\n",
        encoding="utf-8")
    (P / "data" / "meta" / "schedule.csv").write_text(
        "# Cronograma ejecutado en E2 (s desde t0)\nrun,source,start_s,end_s\n" + "\n".join(sch_rows) + "\n",
        encoding="utf-8")
    (P / "data" / "meta" / "runs.csv").write_text(
        "run,udp_loss,capture_drops,notes\n" + "\n".join(run_rows) + "\n", encoding="utf-8")
    (P / "data" / "lab" / "hoja_registro.csv").write_text(
        "run,t0_epoch_C,fin_epoch_C,perdida_udp_A,perdida_udp_B,descartes_tcpdump,notas\n" + "\n".join(hoja) + "\n",
        encoding="utf-8")
    (P / "data" / "lab" / "ventanas.txt").write_text("\n".join(ventanas) + "\n", encoding="utf-8")
    shutil.copy2(a.lab / "versiones_emulacion.txt", P / "data" / "lab" / "versiones_emulacion.txt")
    print(f"Importadas {len(runs)} corridas: {', '.join(runs)}")


if __name__ == "__main__":
    main()
