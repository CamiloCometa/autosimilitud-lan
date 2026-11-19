#!/usr/bin/env python3
"""
Interfaz gráfica del laboratorio "Autosimilitud en trazas de tráfico LAN".

Se abre con doble clic en Iniciar.bat (Windows) o iniciar.sh (Linux/macOS).
Permite:
  1. convertir capturas .pcap/.pcapng a CSV con TShark (sin usar la consola),
  2. elegir los CSV y los archivos auxiliares (ventanas, cronograma, pérdidas),
  3. ejecutar el análisis completo en segundo plano,
  4. ver el registro, la tabla resumen y una vista previa de cada figura.

Toda la lógica de análisis vive en run_analysis.py / autosim/: esta ventana
solo arma los argumentos y muestra los resultados.
"""
from __future__ import annotations

import contextlib
import io
import logging
import math
import os
import queue
import re
import shutil
import subprocess
import sys
import threading
import traceback
from pathlib import Path

import tkinter as tk
from tkinter import filedialog, messagebox, ttk

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))
os.chdir(ROOT)

APP_TITLE = "Autosimilitud en trazas de tráfico LAN"
RUN_RE = re.compile(r"(E\d+)[ _\-]*R(\d+)", re.IGNORECASE)
EXPECTED_RUNS = ("E1_R1", "E1_R2", "E2_R1", "E2_R2")
TSHARK_FILTER = "ip.dst == 192.168.50.13 && (udp.dstport == 5201 || udp.dstport == 5202)"
TSHARK_FIELDS = ("frame.time_epoch", "frame.len", "ip.src", "udp.dstport")
FIT_RE = re.compile(r"^\s*\d*\.?\d+\s*:\s*\d*\.?\d+\s*$")
NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)      # sin consola en Windows

# Colores de la interfaz (texto de estado)
OK_FG, WARN_FG, ERR_FG, MUTED_FG = "#1E6B3A", "#8A5A00", "#B3261E", "#5F5F5F"


# --------------------------------------------------------------------------
# Puentes entre el hilo de trabajo y la ventana
# --------------------------------------------------------------------------
class QueueWriter(io.TextIOBase):
    """Redirige print()/stderr del análisis hacia la ventana."""
    def __init__(self, q: queue.Queue):
        self.q = q

    def write(self, s: str) -> int:
        if s:
            self.q.put(("log", s))
        return len(s)


class QueueHandler(logging.Handler):
    def __init__(self, q: queue.Queue):
        super().__init__()
        self.q = q

    def emit(self, record):
        self.q.put(("log", self.format(record) + "\n"))


def find_tshark() -> str | None:
    found = shutil.which("tshark")
    if found:
        return found
    for base in (os.environ.get("ProgramFiles"), os.environ.get("ProgramFiles(x86)")):
        if base:
            cand = Path(base) / "Wireshark" / "tshark.exe"
            if cand.exists():
                return str(cand)
    for cand in ("/Applications/Wireshark.app/Contents/MacOS/tshark", "/usr/bin/tshark"):
        if Path(cand).exists():
            return cand
    return None


def open_path(path: Path) -> None:
    """Abre un archivo o carpeta con la aplicación predeterminada del sistema."""
    if sys.platform.startswith("win"):
        os.startfile(str(path))                                   # noqa: S606
    elif sys.platform == "darwin":
        subprocess.Popen(["open", str(path)])
    else:
        subprocess.Popen(["xdg-open", str(path)])


def run_name(path: Path) -> str | None:
    m = RUN_RE.search(path.stem)
    return f"{m.group(1).upper()}_R{m.group(2)}" if m else None


# --------------------------------------------------------------------------
# Ventana principal
# --------------------------------------------------------------------------
class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title(APP_TITLE)
        self.geometry("1180x820")
        self.minsize(980, 680)
        if sys.platform.startswith("win"):
            with contextlib.suppress(tk.TclError):
                self.state("zoomed")                                # maximizada en Windows
        self.q: queue.Queue = queue.Queue()
        self.busy = False
        self._preview_img = None
        self._preview_path: Path | None = None
        self._resize_job = None

        self._setup_style()
        self.csv_dir = tk.StringVar(value=str(ROOT / "data" / "raw"))
        self.windows = tk.StringVar()
        self.schedule = tk.StringVar()
        self.meta = tk.StringVar()
        self.out_dir = tk.StringVar(value=str(ROOT / "outputs"))
        self.seed = tk.StringVar(value="20261118")
        self.nperm = tk.StringVar(value="30")
        self.fit_range = tk.StringVar()
        self.want_png = tk.BooleanVar(value=True)
        self.want_pdf = tk.BooleanVar(value=True)

        self._build()
        self.csv_dir.trace_add("write", lambda *_: self._refresh_csv_status())
        self._refresh_csv_status()
        self.after(100, self._poll)
        if (Path(self.out_dir.get()) / "tables" / "summary.csv").exists():
            self._load_results()

    # ---------------------------------------------------------------- estilo
    def _setup_style(self):
        st = ttk.Style(self)
        if sys.platform.startswith("win") and "vista" in st.theme_names():
            st.theme_use("vista")
        elif "clam" in st.theme_names():
            st.theme_use("clam")
        base = ("Segoe UI", 10) if sys.platform.startswith("win") else ("DejaVu Sans", 10)
        self.option_add("*Font", base)
        st.configure("Title.TLabel", font=(base[0], 15, "bold"))
        st.configure("Sub.TLabel", foreground=MUTED_FG)
        st.configure("Section.TLabelframe.Label", font=(base[0], 10, "bold"))
        st.configure("Accent.TButton", font=(base[0], 10, "bold"), padding=(14, 6))
        st.configure("Treeview", rowheight=24)
        st.configure("Treeview.Heading", font=(base[0], 9, "bold"))
        self.base_font = base

    # ---------------------------------------------------------------- layout
    def _build(self):
        outer = ttk.Frame(self, padding=(14, 10, 14, 10))
        outer.pack(fill="both", expand=True)

        head = ttk.Frame(outer)
        head.pack(fill="x")
        tk.Label(head, text=APP_TITLE, font=(self.base_font[0], 16, "bold"), anchor="w").pack(anchor="w")
        ttk.Label(head, style="Sub.TLabel",
                  text="Varianza agregada · control por 30 permutaciones · Δ = 0.05 s y 0.10 s · ventana 600 s"
                  ).pack(anchor="w")
        self.banner = tk.Label(head, text="", fg="white", bg="#8A5A00", anchor="w", padx=8, pady=3,
                               font=(self.base_font[0], 9, "bold"))

        # ---- 1. datos
        data = ttk.LabelFrame(outer, text="1. Datos de entrada", style="Section.TLabelframe", padding=10)
        data.pack(fill="x", pady=(10, 6))
        data.columnconfigure(1, weight=1)

        self._path_row(data, 0, "Carpeta con los CSV", self.csv_dir, kind="dir",
                       extra=("Convertir .pcap a CSV…", self.convert_pcap))
        self.csv_status = tk.Label(data, text="", anchor="w", fg=MUTED_FG, font=(self.base_font[0], 9))
        self.csv_status.grid(row=1, column=1, columnspan=3, sticky="w", pady=(0, 6))
        self._path_row(data, 2, "Ventanas t0 (windows.csv)", self.windows, kind="file",
                       hint="opcional · necesario en E2", clear=True)
        self._path_row(data, 3, "Cronograma E2 (schedule.csv)", self.schedule, kind="file",
                       hint="opcional", clear=True)
        self._path_row(data, 4, "Pérdidas y descartes (runs.csv)", self.meta, kind="file",
                       hint="opcional", clear=True)
        self._path_row(data, 5, "Carpeta de resultados", self.out_dir, kind="dir")

        # ---- 2. opciones
        opt = ttk.LabelFrame(outer, text="2. Opciones", style="Section.TLabelframe", padding=10)
        opt.pack(fill="x", pady=6)
        ttk.Label(opt, text="Semilla").grid(row=0, column=0, sticky="w")
        ttk.Entry(opt, textvariable=self.seed, width=12).grid(row=0, column=1, padx=(6, 18))
        ttk.Label(opt, text="Permutaciones").grid(row=0, column=2, sticky="w")
        ttk.Spinbox(opt, from_=5, to=500, textvariable=self.nperm, width=6).grid(row=0, column=3, padx=(6, 18))
        ttk.Label(opt, text="Tramo fijo (s)").grid(row=0, column=4, sticky="w")
        ttk.Entry(opt, textvariable=self.fit_range, width=11).grid(row=0, column=5, padx=(6, 4))
        ttk.Label(opt, text="vacío = automático · ej. 0.1:6.4", style="Sub.TLabel").grid(row=0, column=6, padx=(0, 18))
        ttk.Checkbutton(opt, text="PNG 300 DPI", variable=self.want_png).grid(row=0, column=7, padx=4)
        ttk.Checkbutton(opt, text="PDF", variable=self.want_pdf).grid(row=0, column=8, padx=4)

        # ---- 3. acciones
        act = ttk.Frame(outer)
        act.pack(fill="x", pady=(8, 6))
        self.btn_run = ttk.Button(act, text="▶  Ejecutar análisis", style="Accent.TButton", command=self.run)
        self.btn_run.pack(side="left")
        self.btn_open = ttk.Button(act, text="Abrir carpeta de resultados", command=self.open_results)
        self.btn_open.pack(side="left", padx=8)
        self.btn_pack = ttk.Button(act, text="📦  Preparar carpeta de entrega", command=self.make_delivery)
        self.btn_pack.pack(side="left", padx=(0, 8))
        self.btn_demo = ttk.Button(act, text="Cargar datos de prueba", command=self.load_demo)
        self.btn_demo.pack(side="left")
        self.status = tk.Label(act, text="Listo.", fg=MUTED_FG, anchor="e")
        self.status.pack(side="right")
        self.progress = ttk.Progressbar(act, mode="indeterminate", length=180)
        self.progress.pack(side="right", padx=10)

        # ---- 4. resultados
        self.nb = ttk.Notebook(outer)
        self.nb.pack(fill="both", expand=True, pady=(4, 0))
        self._build_log_tab()
        self._build_summary_tab()
        self._build_fig_tab()

    def _path_row(self, parent, row, label, var, kind, hint=None, clear=False, extra=None):
        ttk.Label(parent, text=label).grid(row=row, column=0, sticky="w", padx=(0, 10), pady=3)
        ttk.Entry(parent, textvariable=var).grid(row=row, column=1, sticky="ew", pady=3)
        cmd = (lambda: self._pick_dir(var)) if kind == "dir" else (lambda: self._pick_file(var))
        ttk.Button(parent, text="Examinar…", command=cmd).grid(row=row, column=2, padx=(6, 0), pady=3)
        col = 3
        if clear:
            ttk.Button(parent, text="Quitar", width=7, command=lambda: var.set("")).grid(row=row, column=col, padx=(4, 0))
            col += 1
        if extra:
            ttk.Button(parent, text=extra[0], command=extra[1]).grid(row=row, column=col, padx=(6, 0))
        if hint:
            ttk.Label(parent, text=hint, style="Sub.TLabel").grid(row=row, column=col + (0 if not extra else 1),
                                                                  sticky="w", padx=(8, 0))

    def _build_log_tab(self):
        f = ttk.Frame(self.nb, padding=4)
        self.nb.add(f, text="Registro")
        self.log = tk.Text(f, wrap="none", height=12, font=("Consolas", 9) if sys.platform.startswith("win")
                           else ("DejaVu Sans Mono", 9), bg="#FBFBFA", relief="flat")
        ys = ttk.Scrollbar(f, orient="vertical", command=self.log.yview)
        xs = ttk.Scrollbar(f, orient="horizontal", command=self.log.xview)
        self.log.configure(yscrollcommand=ys.set, xscrollcommand=xs.set, state="disabled")
        self.log.tag_configure("warn", foreground=WARN_FG)
        self.log.tag_configure("err", foreground=ERR_FG)
        self.log.tag_configure("ok", foreground=OK_FG)
        self.log.grid(row=0, column=0, sticky="nsew")
        ys.grid(row=0, column=1, sticky="ns")
        xs.grid(row=1, column=0, sticky="ew")
        f.rowconfigure(0, weight=1)
        f.columnconfigure(0, weight=1)
        self._log("Elija la carpeta con los CSV (E1_R1.csv, …) o convierta sus .pcap y pulse "
                  "«Ejecutar análisis».\n", "ok")

    def _build_summary_tab(self):
        f = ttk.Frame(self.nb, padding=4)
        self.nb.add(f, text="Resumen")
        cols = [("run", "Corrida", 70), ("series", "Serie", 55), ("delta_s", "Δ (s)", 55),
                ("range_s", "Tramo (s)", 85), ("beta", "β̂", 70), ("H", "Ĥ", 65), ("r2", "R²", 65),
                ("perm", "Ĥ control: med [mín, máx]", 190), ("control_result", "Resultado del control", 240),
                ("status", "Estado", 95)]
        self.tree = ttk.Treeview(f, columns=[c for c, _, _ in cols], show="headings")
        for c, h, w in cols:
            self.tree.heading(c, text=h)
            self.tree.column(c, width=w, anchor="center" if c not in ("control_result",) else "w", stretch=c == "control_result")
        self.tree.tag_configure("bad", foreground=MUTED_FG)
        self.tree.tag_configure("odd", background="#F6F6F4")
        ys = ttk.Scrollbar(f, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=ys.set)
        self.tree.grid(row=0, column=0, sticky="nsew")
        ys.grid(row=0, column=1, sticky="ns")
        self.summary_note = ttk.Label(f, style="Sub.TLabel", text="Tabla completa: tables/summary.csv y summary.md")
        self.summary_note.grid(row=1, column=0, sticky="w", pady=(4, 0))
        f.rowconfigure(0, weight=1)
        f.columnconfigure(0, weight=1)

    def _build_fig_tab(self):
        f = ttk.Frame(self.nb, padding=4)
        self.nb.add(f, text="Figuras")
        left = ttk.Frame(f)
        left.pack(side="left", fill="y")
        self.fig_list = tk.Listbox(left, width=30, activestyle="none", exportselection=False,
                                   relief="flat", bg="#FBFBFA", highlightthickness=0)
        self.fig_list.pack(fill="y", expand=True)
        self.fig_list.bind("<<ListboxSelect>>", lambda e: self._show_selected())
        self.fig_list.bind("<Double-Button-1>", lambda e: self._open_selected())
        ttk.Button(left, text="Abrir en el visor", command=self._open_selected).pack(fill="x", pady=(6, 0))
        ttk.Label(left, text="Doble clic: abrir a tamaño completo", style="Sub.TLabel").pack(anchor="w", pady=(4, 0))
        self.canvas = tk.Canvas(f, bg="white", highlightthickness=0)
        self.canvas.pack(side="left", fill="both", expand=True, padx=(8, 0))
        self.canvas.bind("<Configure>", lambda e: self._schedule_redraw())
        self._fig_paths: list[Path] = []

    # ---------------------------------------------------------------- utilidades
    def _pick_dir(self, var):
        d = filedialog.askdirectory(initialdir=var.get() or str(ROOT), parent=self)
        if d:
            var.set(str(Path(d)))

    def _pick_file(self, var):
        start = Path(var.get()).parent if var.get() else ROOT / "data" / "meta"
        f = filedialog.askopenfilename(initialdir=str(start), parent=self,
                                       filetypes=[("CSV", "*.csv"), ("Todos", "*.*")])
        if f:
            var.set(str(Path(f)))

    def _log(self, text, tag=None):
        if tag is None:
            low = text.lower()
            tag = "err" if ("error" in low or "traceback" in low) else "warn" if "warning" in low else None
        self.log.configure(state="normal")
        self.log.insert("end", text, tag)
        self.log.see("end")
        self.log.configure(state="disabled")

    def _set_status(self, text, color=MUTED_FG):
        self.status.configure(text=text, fg=color)

    def _set_busy(self, busy: bool, text=""):
        self.busy = busy
        for b in (self.btn_run, self.btn_demo, self.btn_pack):
            b.state(["disabled"] if busy else ["!disabled"])
        if busy:
            self.progress.start(12)
            self._set_status(text)
        else:
            self.progress.stop()

    def _csv_files(self) -> list[Path]:
        d = Path(self.csv_dir.get())
        return sorted(d.glob("*.csv")) if d.is_dir() else []

    def _refresh_csv_status(self):
        d = Path(self.csv_dir.get())
        synthetic = "example" in d.parts
        if synthetic:
            self.banner.configure(text="  Datos SINTÉTICOS de prueba: sirven para verificar el programa, "
                                       "no son mediciones y no deben usarse en el informe.")
            self.banner.pack(fill="x", pady=(6, 0))
        else:
            self.banner.pack_forget()
        if not d.is_dir():
            self.csv_status.configure(text="✗ La carpeta no existe.", fg=ERR_FG)
            return
        files = self._csv_files()
        runs = sorted({r for r in (run_name(p) for p in files) if r})
        bad = [p.name for p in files if not run_name(p)]
        if not runs:
            self.csv_status.configure(fg=ERR_FG, text="✗ No hay CSV con nombre E1_R1.csv, E2_R2.csv, … "
                                                      "Use «Convertir .pcap a CSV…» o copie sus CSV aquí.")
            return
        missing = [r for r in EXPECTED_RUNS if r not in runs]
        txt = "✓ Corridas encontradas: " + ", ".join(runs)
        if missing:
            txt += "   ·   faltan: " + ", ".join(missing)
        if bad:
            txt += "   ·   se ignorarán: " + ", ".join(bad[:4]) + ("…" if len(bad) > 4 else "")
        self.csv_status.configure(text=txt, fg=OK_FG if not missing else WARN_FG)

    # ---------------------------------------------------------------- acciones
    def run(self):
        if self.busy:
            return
        files = [p for p in self._csv_files() if run_name(p)]
        if not files:
            messagebox.showerror(APP_TITLE, "No hay CSV válidos en la carpeta elegida.\n\n"
                                 "Los archivos deben llamarse E1_R1.csv, E1_R2.csv, E2_R1.csv y E2_R2.csv. "
                                 "Si tiene capturas .pcap, use «Convertir .pcap a CSV…».", parent=self)
            return
        fr = self.fit_range.get().strip()
        if fr and not FIT_RE.match(fr):
            messagebox.showerror(APP_TITLE, "El tramo fijo debe tener la forma inicio:fin en segundos, "
                                 "por ejemplo 0.1:6.4 (o dejarse vacío).", parent=self)
            return
        try:
            int(self.seed.get()); n = int(self.nperm.get())
            assert n >= 5
        except (ValueError, AssertionError):
            messagebox.showerror(APP_TITLE, "La semilla y el número de permutaciones (≥ 5) deben ser enteros.",
                                 parent=self)
            return
        fmts = [f for f, on in (("png", self.want_png.get()), ("pdf", self.want_pdf.get())) if on]
        if not fmts:
            messagebox.showerror(APP_TITLE, "Elija al menos un formato de figura (PNG o PDF).", parent=self)
            return
        if any(r.startswith("E2") for r in map(run_name, files)) and not self.windows.get().strip():
            if not messagebox.askyesno(APP_TITLE, "Hay corridas E2 pero no eligió windows.csv.\n\n"
                                       "El taller pide fijar t0 antes de las ráfagas. Sin ese archivo se usará el "
                                       "primer datagrama recibido.\n\n¿Continuar de todos modos?", parent=self):
                return

        argv = [str(p) for p in files]
        for flag, var in (("--windows", self.windows), ("--schedule", self.schedule), ("--meta", self.meta)):
            if var.get().strip():
                if not Path(var.get()).is_file():
                    messagebox.showerror(APP_TITLE, f"No existe el archivo:\n{var.get()}", parent=self)
                    return
                argv += [flag, var.get().strip()]
        argv += ["--out", self.out_dir.get().strip() or str(ROOT / "outputs"),
                 "--seed", self.seed.get().strip(), "--n-perm", self.nperm.get().strip(),
                 "--formats", ",".join(fmts)]
        if fr:
            argv += ["--fit-range", fr.replace(" ", "")]

        self.nb.select(0)
        self._log("\n" + "─" * 70 + "\nEjecutando análisis de " + str(len(files)) + " corridas…\n", "ok")
        self._set_busy(True, "Analizando… (≈ 20–60 s)")
        threading.Thread(target=self._worker, args=(argv,), daemon=True).start()

    def _worker(self, argv):
        handler = QueueHandler(self.q)
        handler.setFormatter(logging.Formatter("%(levelname)-7s %(message)s"))
        root = logging.getLogger()
        root.addHandler(handler)
        root.setLevel(logging.INFO)
        writer = QueueWriter(self.q)
        try:
            import run_analysis
            with contextlib.redirect_stdout(writer), contextlib.redirect_stderr(writer):
                run_analysis.main(argv)
            self.q.put(("done", None))
        except SystemExit as e:
            msg = e.code if isinstance(e.code, str) else "El análisis terminó sin resultados."
            self.q.put(("error", (msg, "")))
        except Exception as e:                                   # noqa: BLE001
            self.q.put(("error", (f"{type(e).__name__}: {e}", traceback.format_exc())))
        finally:
            root.removeHandler(handler)

    def convert_pcap(self):
        if self.busy:
            return
        tshark = find_tshark()
        if not tshark:
            messagebox.showerror(APP_TITLE, "No se encontró TShark.\n\nInstale Wireshark (incluye TShark) desde "
                                 "wireshark.org y vuelva a intentarlo.", parent=self)
            return
        files = filedialog.askopenfilenames(parent=self, title="Elija las capturas (E1_R1.pcap, …)",
                                            initialdir=str(Path.home() / "Downloads"),
                                            filetypes=[("Capturas", "*.pcap *.pcapng"), ("Todos", "*.*")])
        if not files:
            return
        dest = Path(self.csv_dir.get() or ROOT / "data" / "raw")
        if "example" in dest.parts:
            dest = ROOT / "data" / "raw"
        dest.mkdir(parents=True, exist_ok=True)
        self.csv_dir.set(str(dest))
        self.nb.select(0)
        self._set_busy(True, "Convirtiendo capturas…")
        threading.Thread(target=self._convert_worker, args=(tshark, [Path(f) for f in files], dest),
                         daemon=True).start()

    def _convert_worker(self, tshark, files, dest):
        ok = 0
        for f in files:
            name = run_name(f)
            if not name:
                self.q.put(("log", f"WARNING {f.name}: el nombre no indica escenario y repetición "
                                   f"(E1_R1…); se guarda como {f.stem}.csv y no se analizará hasta renombrarlo.\n"))
                name = f.stem
            out = dest / f"{name}.csv"
            cmd = [tshark, "-r", str(f), "-Y", TSHARK_FILTER, "-T", "fields", "-E", "header=y",
                   "-E", "separator=,"]
            for fld in TSHARK_FIELDS:
                cmd += ["-e", fld]
            self.q.put(("log", f"Convirtiendo {f.name} → {out.name} …\n"))
            # Copia de la captura original para la entrega (data/pcap)
            pdir = ROOT / "data" / "pcap"
            pdir.mkdir(parents=True, exist_ok=True)
            pdst = pdir / (f"{name}{f.suffix.lower()}" if run_name(f) else f.name)
            if f.resolve() != pdst.resolve():
                try:
                    shutil.copy2(f, pdst)
                except OSError as e:
                    self.q.put(("log", f"WARNING no se pudo copiar {f.name} a data/pcap: {e}\n"))
            try:
                # Salida binaria directa al archivo: evita el UTF-16 de la redirección de PowerShell.
                with open(out, "wb") as fh:
                    p = subprocess.run(cmd, stdout=fh, stderr=subprocess.PIPE, creationflags=NO_WINDOW)
                if p.returncode != 0:
                    self.q.put(("log", f"ERROR {f.name}: {p.stderr.decode(errors='replace').strip()}\n"))
                    continue
                with open(out, "rb") as fh:
                    n = max(sum(1 for _ in fh) - 1, 0)
                self.q.put(("log", f"   {n:,} paquetes exportados.\n".replace(",", ".")))
                ok += 1
            except Exception as e:                               # noqa: BLE001
                self.q.put(("log", f"ERROR {f.name}: {e}\n"))
        self.q.put(("converted", ok))

    def load_demo(self):
        if self.busy:
            return
        if not messagebox.askyesno(APP_TITLE, "Se generarán trazas SINTÉTICAS (no son del laboratorio) para "
                                   "probar el programa.\n\nLos resultados irán a «outputs_example» y no se "
                                   "mezclan con los suyos. ¿Continuar?", parent=self):
            return
        self._set_busy(True, "Generando datos de prueba…")
        threading.Thread(target=self._demo_worker, daemon=True).start()

    def _demo_worker(self):
        try:
            p = subprocess.run([sys.executable, str(ROOT / "tools" / "generate_synthetic.py"),
                                "--out", str(ROOT / "data" / "example")],
                               capture_output=True, text=True, creationflags=NO_WINDOW)
            self.q.put(("log", (p.stdout or "") + (p.stderr or "")))
            self.q.put(("demo", p.returncode == 0))
        except Exception as e:                                   # noqa: BLE001
            self.q.put(("error", (f"No se pudieron generar los datos: {e}", traceback.format_exc())))

    def make_delivery(self):
        if self.busy:
            return
        out = Path(self.out_dir.get())
        if "example" in out.name:
            messagebox.showerror(APP_TITLE, "La carpeta de resultados actual es la de los datos SINTÉTICOS.\n\n"
                                 "La entrega se arma con los resultados de sus capturas reales: elija la "
                                 "carpeta «outputs» y ejecute el análisis con sus CSV.", parent=self)
            return
        self._set_busy(True, "Preparando carpeta de entrega…")
        self.nb.select(0)
        threading.Thread(target=self._delivery_worker, args=(out,), daemon=True).start()

    def _delivery_worker(self, out):
        try:
            import armar_entrega
            dest, z, checks = armar_entrega.build(out)
            self.q.put(("delivery", (dest, z, checks)))
        except Exception as e:                                   # noqa: BLE001
            self.q.put(("error", (f"{e}", traceback.format_exc() if not isinstance(e, ValueError) else "")))

    def open_results(self):
        d = Path(self.out_dir.get())
        if not d.exists():
            messagebox.showinfo(APP_TITLE, "Todavía no hay resultados en esa carpeta. Ejecute el análisis primero.",
                                parent=self)
            return
        open_path(d)

    # ---------------------------------------------------------------- cola de eventos
    def _poll(self):
        try:
            while True:
                kind, payload = self.q.get_nowait()
                if kind == "log":
                    self._log(payload)
                elif kind == "done":
                    self._set_busy(False)
                    self._set_status("✓ Análisis terminado.", OK_FG)
                    self._log("✓ Análisis terminado. Figuras y tablas guardadas en "
                              f"{self.out_dir.get()}\n", "ok")
                    self._load_results()
                    self.nb.select(1)
                elif kind == "error":
                    msg, tb = payload
                    self._set_busy(False)
                    self._set_status("✗ Error: revise el registro.", ERR_FG)
                    if tb:
                        self._log(tb, "err")
                    self._log(f"✗ {msg}\n", "err")
                    messagebox.showerror(APP_TITLE, msg, parent=self)
                elif kind == "delivery":
                    dest, z, checks = payload
                    self._set_busy(False)
                    bad = [t for st, t in checks if st != "ok"]
                    self._log("\n📦 Carpeta de entrega: " + str(dest) + (f"\n   Zip: {z}" if z else "") + "\n", "ok")
                    for st, t in checks:
                        self._log(f"   {'✓' if st == 'ok' else '✗' if st == 'falta' else '!'} {t}\n",
                                  "ok" if st == "ok" else "err" if st == "falta" else "warn")
                    self._set_status("✓ Entrega completa." if not bad else f"Entrega armada con {len(bad)} pendiente(s).",
                                     OK_FG if not bad else WARN_FG)
                    msg = ("La carpeta de entrega está completa." if not bad else
                           f"Carpeta armada, pero faltan {len(bad)} punto(s):\n\n• " + "\n• ".join(bad[:8]))
                    messagebox.showinfo(APP_TITLE, msg + "\n\nSe abrirá la carpeta.", parent=self)
                    open_path(dest)
                elif kind == "converted":
                    self._set_busy(False)
                    self._refresh_csv_status()
                    self._set_status(f"✓ {payload} captura(s) convertidas.", OK_FG if payload else ERR_FG)
                elif kind == "demo":
                    self._set_busy(False)
                    if payload:
                        ex = ROOT / "data" / "example"
                        self.csv_dir.set(str(ex))
                        self.windows.set(str(ex / "meta" / "windows.csv"))
                        self.schedule.set(str(ex / "meta" / "schedule.csv"))
                        self.meta.set(str(ex / "meta" / "runs.csv"))
                        self.out_dir.set(str(ROOT / "outputs_example"))
                        self._set_status("Datos de prueba listos: pulse «Ejecutar análisis».", WARN_FG)
                    else:
                        self._set_status("✗ No se pudieron generar los datos de prueba.", ERR_FG)
        except queue.Empty:
            pass
        self.after(100, self._poll)

    # ---------------------------------------------------------------- resultados
    def _load_results(self):
        out = Path(self.out_dir.get())
        self.tree.delete(*self.tree.get_children())
        summ = out / "tables" / "summary.csv"
        if summ.exists():
            import pandas as pd
            df = pd.read_csv(summ)

            def f(v, nd=3):
                return "—" if pd.isna(v) else f"{v:.{nd}f}"
            for i, r in enumerate(df.itertuples()):
                perm = "—" if pd.isna(r.perm_H_median) else \
                    f"{r.perm_H_median:.3f} [{r.perm_H_min:.3f}, {r.perm_H_max:.3f}]"
                tags = ["odd"] if i % 2 else []
                if r.status != "estimado":
                    tags.append("bad")
                self.tree.insert("", "end", tags=tags, values=(
                    r.run, r.series, f"{r.delta_s:.2f}", r.range_s, f(r.beta), f(r.H), f(r.r2, 4),
                    perm, r.control_result, r.status))
            self.summary_note.configure(text=f"Tabla completa: {summ}  ·  versión para el informe: summary.md")
        figs = out / "figures"
        order = {"ts": 0, "vt": 1, "psd": 2, "robust": 3, "H": 4}
        self._fig_paths = sorted(figs.glob("*.png"), key=lambda p: (order.get(p.stem.split("_")[0], 9), p.stem)) \
            if figs.exists() else []
        self.fig_list.delete(0, "end")
        for p in self._fig_paths:
            self.fig_list.insert("end", "  " + p.stem)
        if self._fig_paths:
            self.fig_list.selection_set(0)
            self._show_selected()

    def _show_selected(self):
        sel = self.fig_list.curselection()
        if not sel:
            return
        self._preview_path = self._fig_paths[sel[0]]
        self._draw_preview()

    def _schedule_redraw(self):
        if self._resize_job:
            self.after_cancel(self._resize_job)
        self._resize_job = self.after(150, self._draw_preview)

    def _draw_preview(self):
        self._resize_job = None
        self.canvas.delete("all")
        p = self._preview_path
        if not p or not p.exists():
            return
        cw, ch = max(self.canvas.winfo_width(), 50), max(self.canvas.winfo_height(), 50)
        try:
            from PIL import Image, ImageTk            # Pillow ya viene con matplotlib
            im = Image.open(p)
            scale = min((cw - 8) / im.width, (ch - 8) / im.height, 1.0)
            im = im.resize((max(1, int(im.width * scale)), max(1, int(im.height * scale))), Image.LANCZOS)
            self._preview_img = ImageTk.PhotoImage(im)
        except Exception:                                        # noqa: BLE001
            try:                                                 # alternativa sin Pillow
                img = tk.PhotoImage(file=str(p))
                k = max(1, math.ceil(img.width() / cw), math.ceil(img.height() / ch))
                self._preview_img = img.subsample(k) if k > 1 else img
            except tk.TclError:
                self.canvas.create_text(cw / 2, ch / 2, text="No se puede previsualizar; use «Abrir en el visor».")
                return
        self.canvas.create_image(cw / 2, ch / 2, image=self._preview_img, anchor="center")

    def _open_selected(self):
        if self._preview_path and self._preview_path.exists():
            open_path(self._preview_path)


def main():
    try:
        app = App()
    except Exception:                                            # noqa: BLE001
        # Con pythonw no hay consola: se muestra el error en una ventana.
        r = tk.Tk(); r.withdraw()
        messagebox.showerror(APP_TITLE, traceback.format_exc())
        return
    app.mainloop()


if __name__ == "__main__":
    main()
