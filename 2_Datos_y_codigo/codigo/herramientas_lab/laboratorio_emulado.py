#!/usr/bin/env python3
"""
Laboratorio EMULADO: la LAN de la guía con tres hosts y un switch virtuales
(network namespaces de Linux + un bridge, el mismo mecanismo que usa Mininet).
Ejecuta iperf3 y tcpdump reales, como en la guía, y deja todo lo que pide el
entregable: capturas .pcap, t0 de cada ventana, cronogramas de E2, pérdidas
UDP (iperf3), descartes de captura (tcpdump), versiones y registro de comandos.

Requiere Linux y permisos de root (sudo):  iproute2, iperf3, tcpdump.

    sudo python3 laboratorio_emulado.py --out lab_emulado            # 4 corridas en paralelo
    sudo python3 laboratorio_emulado.py --runs E2_R1 --duration 60   # prueba corta

Topología de cada corrida (redes aisladas entre sí):

    A (192.168.50.11) ─┐
                       ├─ bridge "switch" ── C (192.168.50.13)  iperf3 -s :5201 :5202 + tcpdump
    B (192.168.50.12) ─┘

Los enlaces son veth sin limitación de ancho de banda (igual que Mininet por
defecto). Todos los nodos comparten el reloj del anfitrión, así que el t0
registrado en C y los tiempos de los cronogramas están en la misma escala.
"""
from __future__ import annotations

import argparse
import json
import random
import shlex
import signal
import subprocess
import threading
import time
from datetime import datetime, timezone
from pathlib import Path

NS = 1_000_000_000
IPS = {"A": "192.168.50.11", "B": "192.168.50.12", "C": "192.168.50.13"}
PORTS = {"A": 5201, "B": 5202}
FILTER = "udp and dst host 192.168.50.13 and (dst port 5201 or dst port 5202)"
IPERF = ["-u", "-b", "4M", "-l", "1200"]

_log_lock = threading.Lock()


def epoch_ns_str(t_ns: int) -> str:
    return f"{t_ns // NS}.{t_ns % NS:09d}"


class Run:
    def __init__(self, run: str, out: Path, duration: int, seed: int):
        self.run, self.out, self.T, self.seed = run, out / run, duration, seed
        self.out.mkdir(parents=True, exist_ok=True)
        tag = run.lower().replace("_", "")             # e1r1
        self.ns = {n: f"{tag}{n.lower()}" for n in "ABC"}
        self.br = f"br{tag}"
        self.reglog = self.out / "registro_comandos.txt"
        self.procs: list[subprocess.Popen] = []

    # ---------------------------------------------------------------- utilidades
    def log(self, msg: str):
        line = f"[{datetime.now():%H:%M:%S}] {msg}"
        with _log_lock:
            print(f"{self.run}: {msg}", flush=True)
        with open(self.reglog, "a", encoding="utf-8") as f:
            f.write(line + "\n")

    def sh(self, cmd: str, node: str | None = None, check=True, capture=False) -> str:
        full = f"ip netns exec {self.ns[node]} {cmd}" if node else cmd
        with open(self.reglog, "a", encoding="utf-8") as f:
            f.write(f"$ {('[' + node + '] ') if node else ''}{cmd}\n")
        r = subprocess.run(shlex.split(full), capture_output=True, text=True)
        if check and r.returncode != 0:
            raise RuntimeError(f"{full}\n{r.stderr}")
        return r.stdout + (r.stderr if capture else "")

    # ---------------------------------------------------------------- topología
    def build(self):
        self.log("creando topología: 3 hosts + switch (bridge)")
        self.sh(f"ip link add {self.br} type bridge")
        self.sh(f"ip link set {self.br} up")
        for n in "ABC":
            ns, host_if = self.ns[n], f"{self.ns[n]}-s"
            self.sh(f"ip netns add {ns}")
            self.sh(f"ip link add {ns} type veth peer name {host_if}")
            self.sh(f"ip link set {ns} netns {ns}")
            self.sh(f"ip link set {host_if} master {self.br}")
            self.sh(f"ip link set {host_if} up")
            self.sh(f"ip link set {ns} name eth0", n)
            self.sh(f"ip addr add {IPS[n]}/24 dev eth0", n)
            self.sh("ip link set eth0 up", n)
            self.sh("ip link set lo up", n)
        time.sleep(1.0)
        for n in "AB":
            out = self.sh("ping -c 5 -i 0.2 192.168.50.13", n, capture=True)
            (self.out / f"ping_{n}_a_C.txt").write_text(out, encoding="utf-8")
        for n in "ABC":
            info = self.sh("ip -br addr", n, capture=True)
            (self.out / f"interfaces_{n}.txt").write_text(info, encoding="utf-8")

    def teardown(self):
        for p in self.procs:
            if p.poll() is None:
                p.terminate()
        for n in "ABC":
            subprocess.run(["ip", "netns", "del", self.ns[n]], capture_output=True)
        subprocess.run(["ip", "link", "del", self.br], capture_output=True)

    # ---------------------------------------------------------------- servicios en C
    def start_servers(self):
        for port in (5201, 5202):
            cmd = f"ip netns exec {self.ns['C']} iperf3 -s -p {port}"
            with open(self.reglog, "a") as f:
                f.write(f"$ [C] iperf3 -s -p {port}\n")
            self.procs.append(subprocess.Popen(shlex.split(cmd), stdout=subprocess.DEVNULL,
                                               stderr=subprocess.DEVNULL))
        time.sleep(1.0)

    def start_capture(self) -> subprocess.Popen:
        pcap = self.out / f"{self.run}.pcap"
        cmd = ["ip", "netns", "exec", self.ns["C"], "tcpdump", "-i", "eth0", "-nn", "-s", "128",
               "-w", str(pcap), FILTER]
        with open(self.reglog, "a") as f:
            f.write(f"$ [C] tcpdump -i eth0 -nn -s 128 -w {pcap.name} '{FILTER}'\n")
        self.tcpdump_err = open(self.out / "tcpdump_stderr.txt", "w")
        p = subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=self.tcpdump_err)
        self.procs.append(p)
        time.sleep(1.5)
        return p

    def stop_capture(self, p: subprocess.Popen) -> str:
        p.send_signal(signal.SIGINT)
        p.wait(timeout=20)
        self.tcpdump_err.close()
        txt = (self.out / "tcpdump_stderr.txt").read_text()
        drops = next((l.split()[0] for l in txt.splitlines() if "dropped by kernel" in l), "?")
        return drops

    def iperf(self, node: str, seconds: int, label: str) -> dict:
        args = f"iperf3 -c 192.168.50.13 -p {PORTS[node]} {' '.join(IPERF)} -t {seconds} --json"
        out = self.sh(args, node, check=False)
        (self.out / f"iperf_{label}.json").write_text(out, encoding="utf-8")
        try:
            j = json.loads(out)
            end = j.get("end", {})
            s = end.get("sum_received") or end.get("sum") or {}
            return {"packets": s.get("packets"), "lost": s.get("lost_packets"),
                    "lost_pct": s.get("lost_percent"), "error": j.get("error")}
        except json.JSONDecodeError:
            return {"packets": None, "lost": None, "lost_pct": None, "error": "salida no JSON"}

    # ---------------------------------------------------------------- escenarios
    def e1(self):
        cap = self.start_capture()
        t_start = time.time_ns()
        self.log(f"E1: inicio (reloj de C) {epoch_ns_str(t_start)}; A envía 600 s a :5201")
        res = self.iperf("A", self.T, "A")
        time.sleep(3)
        t_end = time.time_ns()
        drops = self.stop_capture(cap)
        self.log(f"E1: fin {epoch_ns_str(t_end)}; pérdida UDP {res['lost']}/{res['packets']} "
                 f"({res['lost_pct']} %); descartes de captura {drops}")
        return {"t0": None, "t_start": epoch_ns_str(t_start), "t_end": epoch_ns_str(t_end),
                "loss": {"A": res}, "drops": drops, "schedule": []}

    def plan(self, node: str) -> list[tuple[int, int]]:
        """Cronograma ON/OFF: silencio inicial 2–6 s, ráfagas y pausas de 1–20 s,
        silencio final ≥ 8 s. Semilla distinta por corrida y nodo (reproducible)."""
        rng = random.Random(f"{self.seed}|{self.run}|{node}")
        t, out = rng.randint(2, 6), []
        while True:
            dur = rng.randint(1, 20)
            if t + dur > self.T - 8:
                break
            out.append((t, t + dur))
            t += dur + rng.randint(1, 20)
        return out

    def _bursts(self, node: str, t0_ns: int, plan, results: list):
        for k, (a, b) in enumerate(plan):
            wait = (t0_ns + a * NS - time.time_ns()) / NS
            if wait > 0:
                time.sleep(wait)
            r = self.iperf(node, b - a, f"{node}_{k:02d}")
            results.append((a, b, r))

    def e2(self):
        cap = self.start_capture()
        plans = {n: self.plan(n) for n in "AB"}
        t0 = time.time_ns() + int(0.5 * NS)          # t0 fijado ANTES de la primera ráfaga
        self.log(f"E2: t0 (reloj de C) = {epoch_ns_str(t0)}; ráfagas A={len(plans['A'])}, B={len(plans['B'])}")
        res = {"A": [], "B": []}
        th = [threading.Thread(target=self._bursts, args=(n, t0, plans[n], res[n])) for n in "AB"]
        for t in th:
            t.start()
        for t in th:
            t.join()
        wait = (t0 + (self.T + 5) * NS - time.time_ns()) / NS   # ventana completa + 5 s
        if wait > 0:
            time.sleep(wait)
        t_end = time.time_ns()
        drops = self.stop_capture(cap)
        loss = {}
        for n in "AB":
            pk = sum((r["packets"] or 0) for _, _, r in res[n])
            lo = sum((r["lost"] or 0) for _, _, r in res[n])
            loss[n] = {"packets": pk, "lost": lo, "lost_pct": 100 * lo / pk if pk else None,
                       "error": "; ".join(sorted({str(r["error"]) for _, _, r in res[n] if r["error"]})) or None}
        self.log(f"E2: fin {epoch_ns_str(t_end)}; pérdidas A {loss['A']['lost']}/{loss['A']['packets']}, "
                 f"B {loss['B']['lost']}/{loss['B']['packets']}; descartes de captura {drops}")
        sched = [(n, a, b) for n in "AB" for a, b, _ in sorted(res[n])]
        return {"t0": epoch_ns_str(t0), "t_start": epoch_ns_str(t0), "t_end": epoch_ns_str(t_end),
                "loss": loss, "drops": drops, "schedule": sched}

    def execute(self) -> dict:
        try:
            self.build()
            self.start_servers()
            res = self.e1() if self.run.startswith("E1") else self.e2()
        finally:
            self.teardown()
        res["run"] = self.run
        (self.out / "resultado.json").write_text(json.dumps(res, indent=2), encoding="utf-8")
        return res


def versions(out: Path):
    def q(cmd):
        r = subprocess.run(cmd, shell=True, capture_output=True, text=True)
        return (r.stdout or r.stderr).strip().splitlines()[0] if (r.stdout or r.stderr) else "?"
    txt = "\n".join([
        f"== Anfitrión de la emulación   fecha: {datetime.now(timezone.utc):%Y-%m-%d %H:%M:%S} UTC",
        q("grep PRETTY_NAME /etc/os-release"), f"kernel: {q('uname -r')}",
        q("iperf3 --version"), q("tcpdump --version 2>&1"), q("tshark --version"),
        "Nodos: network namespaces A, B, C; switch: Linux bridge; enlaces: veth sin límite de tasa",
    ])
    (out / "versiones_emulacion.txt").write_text(txt + "\n", encoding="utf-8")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", type=Path, default=Path("lab_emulado"))
    ap.add_argument("--runs", nargs="+", default=["E1_R1", "E1_R2", "E2_R1", "E2_R2"])
    ap.add_argument("--duration", type=int, default=600)
    ap.add_argument("--seed", type=int, default=20261118)
    ap.add_argument("--sequential", action="store_true", help="una corrida tras otra (por defecto en paralelo)")
    a = ap.parse_args()
    a.out.mkdir(parents=True, exist_ok=True)
    versions(a.out)
    runs = [Run(r, a.out, a.duration, a.seed) for r in a.runs]
    results = {}

    def go(r):
        results[r.run] = r.execute()
    if a.sequential:
        for r in runs:
            go(r)
    else:
        th = [threading.Thread(target=go, args=(r,)) for r in runs]
        for t in th:
            t.start()
            time.sleep(2)
        for t in th:
            t.join()
    (a.out / "resumen_corridas.json").write_text(json.dumps(results, indent=2), encoding="utf-8")
    print("LISTO", flush=True)


if __name__ == "__main__":
    main()
