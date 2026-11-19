#!/usr/bin/env python3
"""
Arma la carpeta de entrega del taller con los cuatro entregables de la guía
y una lista de verificación automática (LEEME.md), y la comprime en un .zip.

    python armar_entrega.py                 # usa outputs/ (resultados reales)
    python armar_entrega.py --outputs otra_carpeta

Estructura generada (dentro del proyecto):

ENTREGA_Autosimilitud_LAN/
├── LEEME.md                         índice + lista de verificación
├── 1_Montaje_y_adquisicion/         diagrama, comandos, hoja de registro,
│   └── registros_nodos/             ventanas, cronograma, pérdidas, versiones…
├── 2_Datos_y_codigo/
│   ├── capturas_pcap/   csv/   codigo/   COMO_EJECUTAR.md
├── 3_Graficas_y_tabla/              figuras/ (PNG+PDF), tablas/, params.json
└── 4_Informe/                       informe .docx / .pdf
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import shutil
import zipfile
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent
NAME = "ENTREGA_Autosimilitud_LAN"
RUNS = ("E1_R1", "E1_R2", "E2_R1", "E2_R2")
RUN_RE = re.compile(r"(E\d+)[ _\-]*R(\d+)", re.IGNORECASE)
CODE_ITEMS = ("autosim", "tools", "herramientas_lab", "run_analysis.py", "app_gui.py", "armar_entrega.py",
              "requirements.txt", "README.md", "Iniciar.bat", "iniciar.sh")


def _copy(src: Path, dst: Path) -> bool:
    if not src.exists():
        return False
    dst.parent.mkdir(parents=True, exist_ok=True)
    if src.is_dir():
        shutil.copytree(src, dst, dirs_exist_ok=True,
                        ignore=shutil.ignore_patterns("__pycache__", "*.pyc", "LEEME.txt"))
    else:
        shutil.copy2(src, dst)
    return True


def _data_rows(path: Path) -> int:
    """Filas de datos de un CSV (sin comentarios ni encabezado)."""
    if not path.exists():
        return 0
    lines = [l for l in path.read_text(encoding="utf-8", errors="replace").splitlines()
             if l.strip() and not l.lstrip().startswith("#")]
    return max(len(lines) - 1, 0)


def _runs_in(files) -> set[str]:
    out = set()
    for f in files:
        m = RUN_RE.search(Path(f).stem)
        if m:
            out.add(f"{m.group(1).upper()}_R{m.group(2)}")
    return out


def _docx_pending(path: Path) -> bool:
    try:
        with zipfile.ZipFile(path) as z:
            return "PENDIENTE" in z.read("word/document.xml").decode("utf-8", errors="ignore")
    except Exception:                                            # noqa: BLE001
        return False


def build(outputs: Path | None = None, project: Path = ROOT, make_zip: bool = True):
    """Devuelve (carpeta, zip | None, lista de (estado, texto)). estado ∈ {'ok','falta','aviso'}."""
    outputs = Path(outputs or project / "outputs")
    if "example" in outputs.name or "example" in outputs.parts[-1]:
        raise ValueError("Esa carpeta de resultados es de los datos SINTÉTICOS de prueba. "
                         "La entrega debe armarse con los resultados de sus capturas reales (outputs).")

    dest = project / NAME
    if dest.exists():
        shutil.rmtree(dest)
    m1, m2, m3, m4 = (dest / "1_Montaje_y_adquisicion", dest / "2_Datos_y_codigo",
                      dest / "3_Graficas_y_tabla", dest / "4_Informe")
    for d in (m1, m2, m3, m4):
        d.mkdir(parents=True)
    checks: list[tuple[str, str]] = []

    # ---------------- 1. Montaje y adquisición
    _copy(project / "docs" / "diagrama_red.png", m1 / "diagrama_red.png")
    _copy(project / "docs" / "diagrama_red.pdf", m1 / "diagrama_red.pdf")
    _copy(project / "docs" / "comandos_laboratorio.md", m1 / "comandos_laboratorio.md")
    lab = project / "data" / "lab"
    lab_files = [p for p in lab.glob("*") if p.is_file() and p.name != "LEEME.txt"] if lab.exists() else []
    hoja = lab / "hoja_registro.csv"
    _copy(hoja if hoja.exists() else project / "docs" / "hoja_registro.csv", m1 / "hoja_registro.csv")
    for p in lab_files:
        if p.name != "hoja_registro.csv":
            _copy(p, m1 / "registros_nodos" / p.name)
    meta = project / "data" / "meta"
    for src, name in (("windows.csv", "ventanas_windows.csv"), ("schedule.csv", "cronograma_schedule.csv"),
                      ("runs.csv", "perdidas_y_descartes_runs.csv")):
        _copy(meta / src, m1 / name)

    vers = [p for p in lab_files if p.name.startswith("versiones_")]
    regs = [p for p in lab_files if p.name.startswith("registro_")]
    checks.append(("ok", "Diagrama de la red (PNG y PDF)"))
    ifs = {}
    with_if = project / "docs" / "diagrama_red.json"
    if with_if.exists():
        ifs = json.loads(with_if.read_text(encoding="utf-8"))
    real_if = ifs and all("<" not in str(v) for v in ifs.values())
    checks.append(("ok" if real_if else "aviso",
                   "Interfaces reales en el diagrama" + ("" if real_if else
                   ": ejecute  python tools/dibujar_diagrama_red.py --if-a <A> --if-b <B> --if-c <C>")))
    emul = any(p.name.startswith("versiones_emulacion") for p in vers)
    checks.append(("ok" if len(vers) >= 3 or emul else "falta",
                   "Versiones del anfitrión de la red emulada" if emul else
                   f"Versiones de los 3 nodos (versiones_*.txt): {len(vers)}/3"))
    checks.append(("ok" if regs else "falta", f"Registros de terminal (registro_*.txt): {len(regs)}"))
    n_win = _data_rows(meta / "windows.csv")
    checks.append(("ok" if n_win >= 2 else "falta", f"t0 de las ventanas E2 en windows.csv: {n_win} fila(s)"))
    n_sch = _data_rows(meta / "schedule.csv")
    checks.append(("ok" if n_sch else "falta", f"Cronograma de E2 en schedule.csv: {n_sch} ráfaga(s)"))
    n_runs = _data_rows(meta / "runs.csv")
    checks.append(("ok" if n_runs >= 4 else "falta", f"Pérdidas UDP y descartes en runs.csv: {n_runs}/4 corridas"))

    # ---------------- 2. Datos y código
    pcaps = sorted((project / "data" / "pcap").glob("*.pcap*"))
    for p in pcaps:
        _copy(p, m2 / "capturas_pcap" / p.name)
    csvs = sorted((project / "data" / "raw").glob("*.csv"))
    for p in csvs:
        _copy(p, m2 / "csv" / p.name)
    for item in CODE_ITEMS:
        _copy(project / item, m2 / "codigo" / item)
    (m2 / "COMO_EJECUTAR.md").write_text(
        "# Cómo reproducir el análisis\n\n"
        "Desde esta carpeta (`2_Datos_y_codigo`), con Python 3.9+:\n\n"
        "```\npip install -r codigo/requirements.txt\n"
        "python codigo/run_analysis.py csv "
        "--windows ../1_Montaje_y_adquisicion/ventanas_windows.csv "
        "--schedule ../1_Montaje_y_adquisicion/cronograma_schedule.csv "
        "--meta ../1_Montaje_y_adquisicion/perdidas_y_descartes_runs.csv --out resultados\n```\n\n"
        "O con doble clic en `codigo/Iniciar.bat` (Windows) y eligiendo la carpeta `csv` en la ventana.\n"
        "Los resultados deben coincidir con `3_Graficas_y_tabla` (semilla fija 20261118).\n",
        encoding="utf-8")
    got_p, got_c = _runs_in(pcaps), _runs_in(csvs)
    synth = {hashlib.sha256(p.read_bytes()).hexdigest() for p in (project / "data" / "example").glob("*.csv")}
    fake = [p.name for p in csvs if hashlib.sha256(p.read_bytes()).hexdigest() in synth]
    if fake:
        checks.append(("falta", "Estos CSV son los SINTÉTICOS de prueba, no mediciones: " + ", ".join(fake)))
    checks.append(("ok" if got_p >= set(RUNS) else "falta",
                   "Capturas originales .pcap: " + (", ".join(sorted(got_p)) or "ninguna")))
    checks.append(("ok" if got_c >= set(RUNS) else "falta",
                   "CSV exportados: " + (", ".join(sorted(got_c)) or "ninguno")))
    checks.append(("ok", "Código y guía de ejecución"))

    # ---------------- 3. Gráficas y tabla
    figs = sorted((outputs / "figures").glob("*.*")) if (outputs / "figures").exists() else []
    _copy(outputs / "figures", m3 / "figuras")
    _copy(outputs / "tables", m3 / "tablas")
    _copy(outputs / "params.json", m3 / "params.json")
    n_png = sum(1 for f in figs if f.suffix == ".png")
    checks.append(("ok" if n_png >= 19 else "falta",
                   f"Figuras PNG (series, log-log, periodicidad, robustez, resumen): {n_png}/19"))
    summ = outputs / "tables" / "summary.md"
    checks.append(("ok" if summ.exists() else "falta", "Tabla resumen por corrida (summary.md / .csv)"))
    if (outputs / "params.json").exists() and csvs:
        # Los resultados deben corresponder exactamente a los CSV actuales (SHA-256).
        used = {i["file"]: i["sha256"] for i in json.loads((outputs / "params.json").read_text(
            encoding="utf-8")).get("inputs", [])}
        now = {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in csvs}
        same = all(used.get(k) == v for k, v in now.items() if _runs_in([k]))
        checks.append(("ok" if same else "aviso",
                       "Resultados generados con los CSV actuales (SHA-256)" if same else
                       "Los resultados no corresponden a los CSV actuales: vuelva a ejecutar el análisis"))

    # ---------------- 4. Informe
    reps = [p for p in (project / "informe").glob("*") if p.suffix.lower() in (".docx", ".pdf")] \
        if (project / "informe").exists() else []
    for p in reps:
        _copy(p, m4 / p.name)
    if not reps:
        checks.append(("falta", "Informe (.docx o .pdf) en la carpeta informe/"))
    else:
        pend = [p.name for p in reps if p.suffix.lower() == ".docx" and _docx_pending(p)]
        checks.append(("aviso" if pend else "ok",
                       "Informe: " + ", ".join(p.name for p in reps) +
                       (" — aún tiene campos [PENDIENTE]" if pend else "")))

    # ---------------- LEEME
    icon = {"ok": "✅", "falta": "❌", "aviso": "⚠️"}
    n_bad = sum(s != "ok" for s, _ in checks)
    lines = [
        "# Entrega — Autosimilitud en trazas de tráfico LAN", "",
        f"Generada: {datetime.now():%Y-%m-%d %H:%M}  ·  "
        + ("**completa**" if n_bad == 0 else f"**{n_bad} punto(s) pendiente(s)**"), "",
        "| Carpeta | Entregable de la guía |", "|---|---|",
        "| `1_Montaje_y_adquisicion/` | Diagrama, configuraciones, versiones, comandos, cronogramas y ventanas |",
        "| `2_Datos_y_codigo/` | Capturas PCAP, CSV exportados, código reproducible y cómo ejecutarlo |",
        "| `3_Graficas_y_tabla/` | Series en 3 resoluciones, log–log con control, robustez y tabla por corrida |",
        "| `4_Informe/` | Informe con discusión y conclusiones por escenario |", "",
        "## Lista de verificación", "",
    ] + [f"- {icon[s]} {t}" for s, t in checks]
    (dest / "LEEME.md").write_text("\n".join(lines) + "\n", encoding="utf-8")

    zpath = None
    if make_zip:
        zpath = Path(shutil.make_archive(str(project / NAME), "zip", root_dir=project, base_dir=NAME))
    return dest, zpath, checks


def main():
    ap = argparse.ArgumentParser(description="Arma la carpeta de entrega del taller.")
    ap.add_argument("--outputs", type=Path, default=None, help="carpeta de resultados (def. outputs)")
    ap.add_argument("--no-zip", action="store_true")
    a = ap.parse_args()
    dest, z, checks = build(a.outputs, make_zip=not a.no_zip)
    for s, t in checks:
        print({"ok": "[OK]   ", "falta": "[FALTA]", "aviso": "[AVISO]"}[s], t)
    print(f"\nCarpeta: {dest}" + (f"\nZip:     {z}" if z else ""))


if __name__ == "__main__":
    main()
