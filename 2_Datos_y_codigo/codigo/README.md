# Autosimilitud en trazas de tráfico LAN — análisis reproducible

Reconstruye las series de bytes por intervalo a partir de los CSV de TShark, estima
*H* por varianza agregada, contrasta con 30 permutaciones, repite con Δ = 0.10 s y
genera figuras (PNG 300 DPI + PDF vectorial) y tablas sin interacción manual.

## Estructura

```
autosimilitud_lan/
├── Iniciar.bat                # doble clic en Windows: prepara el entorno y abre la ventana
├── iniciar.sh                 # lo mismo en Linux/macOS
├── app_gui.py                 # interfaz gráfica (Tkinter)
├── armar_entrega.py           # arma ENTREGA_Autosimilitud_LAN/ + .zip con lista de verificación
├── run_analysis.py            # CLI: orquesta todo el análisis
├── requirements.txt
├── autosim/
│   ├── config.py              # IPs, puertos, ventana, escalas, criterios, semilla
│   ├── trace_io.py            # lectura de CSV (tiempos en ns enteros), ventanas, cronograma, metadatos
│   ├── series.py              # t0, X_k en intervalos semiabiertos, bloques, tasa (B/s), ráfagas ON
│   ├── hurst.py               # V(m), selección de tramo estable, Ĥ, sensibilidad
│   ├── control.py             # 30 permutaciones con semillas derivadas y documentadas
│   ├── plots.py               # estilo Okabe-Ito y las 4 familias de figuras
│   └── report.py              # summary.csv/.md, robustness.csv
├── tools/                     # generate_synthetic.py (pruebas), dibujar_diagrama_red.py
├── herramientas_lab/          # rafagas.sh y registrar_nodo.sh para los nodos del laboratorio
├── docs/                      # diagrama de la red, comandos del laboratorio, hoja de registro
├── informe/                   # informe .docx (reemplazar por la versión final)
├── data/
│   ├── pcap/                  # ← capturas originales (el botón de conversión las copia aquí)
│   ├── raw/                   # ← E1_R1.csv, E1_R2.csv, E2_R1.csv, E2_R2.csv
│   ├── lab/                   # ← versiones_*.txt, registro_*.txt, cronogramas, logs del laboratorio
│   └── meta/                  # windows.csv, schedule.csv, runs.csv (plantillas vacías)
└── outputs/
    ├── figures/               # ts_*, vt_*, robust_*, H_summary (.png + .pdf)
    ├── tables/                # summary.csv/.md, variance_curves.csv, fit_candidates.csv,
    │                          # robustness.csv, run_info.csv, activity_E2.csv
    └── params.json            # parámetros, semillas, versiones y SHA-256 de cada CSV
```

## Uso con doble clic (sin consola)

1. **Windows:** doble clic en `Iniciar.bat`. **Linux/macOS:** doble clic en `iniciar.sh` (o `./iniciar.sh`).
   La primera vez crea `.venv` e instala las dependencias (1–3 min); después abre la ventana directamente.
2. En la ventana:
   - **Convertir .pcap a CSV…**: elige sus capturas y las exporta con TShark a `data/raw` (requiere Wireshark).
   - Revise que aparezca "✓ Corridas encontradas: E1_R1, E1_R2, E2_R1, E2_R2".
   - Elija `windows.csv` (t0 de E2) y, si los tiene, `schedule.csv` y `runs.csv`.
   - **▶ Ejecutar análisis**. Al terminar, las pestañas **Resumen** y **Figuras** muestran la tabla y una vista
     previa de cada figura (doble clic para abrirla a tamaño completo).
   - **Cargar datos de prueba** genera trazas sintéticas en `data/example` y guarda sus resultados en
     `outputs_example` (una franja naranja recuerda que no son mediciones).

Al final, **📦 Preparar carpeta de entrega** arma `ENTREGA_Autosimilitud_LAN/` (y su .zip) con los cuatro
entregables de la guía y un `LEEME.md` con la lista de verificación: marca lo que falta (capturas, versiones,
cronograma, informe con campos [PENDIENTE]…) y se niega a usar resultados de los datos sintéticos.

Para tener un acceso directo en el escritorio: clic derecho sobre `Iniciar.bat` → *Enviar a* → *Escritorio
(crear acceso directo)*.

## Ejecución desde la terminal

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt

# 1) Exportar cada captura (comando del taller), nombrando E<escenario>_R<repetición>.csv
tshark -r E1_R1.pcap -Y 'ip.dst == 192.168.50.13 && (udp.dstport == 5201 || udp.dstport == 5202)' \
  -T fields -E header=y -E separator=, \
  -e frame.time_epoch -e frame.len -e ip.src -e udp.dstport > data/raw/E1_R1.csv

# 2) Analizar
python run_analysis.py data/raw/ \
    --windows data/meta/windows.csv \
    --schedule data/meta/schedule.csv \
    --meta data/meta/runs.csv \
    --out outputs
```

Prueba rápida sin datos reales:

```bash
python tools/generate_synthetic.py --out data/example
python run_analysis.py data/example --windows data/example/meta/windows.csv \
    --schedule data/example/meta/schedule.csv --meta data/example/meta/runs.csv --out outputs_example
```

### Archivos auxiliares (opcionales, pero recomendados)

| Archivo | Columnas | Uso |
|---|---|---|
| `windows.csv` | `run,t0[,duration_s]` | t0 con el reloj de C (epoch con 9 decimales o ISO con zona). **Obligatorio en la práctica para E2** (inicio fijado antes de las ráfagas). Si falta, E1 usa el primer datagrama (criterio del taller) y E2 usa el primer datagrama con advertencia. |
| `schedule.csv` | `run,source,start_s,end_s` | Cronograma declarado de E2 (segundos desde t0). Se dibuja sobre las ráfagas observadas y se calcula la concordancia. |
| `runs.csv` | `run,udp_loss,capture_drops,…` | Texto libre de los reportes de iperf3 y del capturador; se copia a la tabla resumen. Mantengan separadas pérdidas de red y descartes de captura. |

### Opciones útiles

| Opción | Efecto |
|---|---|
| `--fit-range 0.1:6.4` | Fija el tramo en segundos para todas las series (comparación en el mismo rango físico). |
| `--max-rmse 0.03`, `--max-local-dev 0.20` | Criterios de "tramo linealmente estable" (ver abajo). |
| `--r2-min 0.98` | Añade un umbral de R² (desactivado por defecto; ver nota). |
| `--seed 20261118`, `--n-perm 30` | Semilla base y número de permutaciones. |
| `--formats png,pdf`, `--dpi 300` | Formatos de salida. |

## Qué hace el código, paso a paso

1. **Tiempo exacto.** `frame.time_epoch` se lee como texto y se pasa a nanosegundos enteros; la
   asignación a `[t0 + kΔ, t0 + (k+1)Δ)` se hace con división entera, así que ningún paquete en
   un borde cae en el intervalo equivocado. Los intervalos vacíos quedan en 0.
2. **Series.** E1: A (`192.168.50.11 → :5201`). E2: A, B (`192.168.50.12 → :5202`) y A+B con el
   mismo t0. Paquetes con otro origen/puerto se cuentan y se excluyen (`run_info.csv`).
3. **Varianza agregada.** Para cada m ∈ {1,…,256}: M_m = ⌊N/m⌋ bloques completos, V(m) con
   `ddof=1`. Se excluyen (y documentan) escalas con V = 0 o M_m < 30. Con Δ = 0.10 s (N = 6000)
   la escala m = 256 queda siempre excluida (M = 23).
4. **Tramo.** Se evalúan todos los tramos de ≥ 4 escalas válidas consecutivas
   (`fit_candidates.csv`). Un tramo es estable si: RMSE de residuos ≤ 0.03 décadas,
   todas las pendientes locales a menos de 0.20 de β̂, y 0 ≤ Ĥ ≤ 1. Se elige el más largo
   (empate: menor RMSE). Si ninguno cumple, la serie queda **"sin sustento"** y solo se
   comparan curvas con el control.
   *Nota sobre R²:* se reporta siempre, pero no se usa como criterio por defecto: con una curva
   casi plana (β̂ ≈ 0) los puntos pueden estar perfectamente alineados y aun así tener R² bajo,
   porque hay poca variación que explicar.
5. **Sensibilidad.** Ĥ al retirar la escala inferior y la superior del tramo (si quedan ≥ 4).
6. **Control.** 30 permutaciones de X_k por serie. La semilla de cada serie es
   `SeedSequence([seed_base, crc32("<run>|<serie>|<Δ>")])` y queda en `summary.csv`. Ĥ de cada
   permutación se calcula en el mismo tramo. La permutación conserva V(1) exactamente
   (comprobación: `log10_ratio_V_vs_perm = 0` en m = 1).
7. **Robustez.** Todo se repite con Δ = 0.10 s; `robustness.csv` compara Ĥ entre Δ y entre
   repeticiones y la diferencia relativa de Var(tasa) en escalas físicas comunes.

## Figuras

| Archivo | Contenido |
|---|---|
| `ts_<run>` | Tasa en **bytes/s** a 0.05, 0.4 y 3.2 s con eje vertical común, media y CV por resolución. En E2: A y B apiladas (el borde superior es A+B) y una franja con cronograma declarado (rayado), ráfagas observadas (sólido) y solapamientos A∧B. E1 incluye la tasa nominal de trama (≈ 517.5 kB/s para `-b 4M -l 1200` con 42 B de cabeceras). |
| `vt_<run>_d005`, `vt_<run>_d010` | log10 V(m) vs log10(mΔ), un panel por serie: puntos incluidos (rellenos), válidos fuera del tramo (huecos), excluidos (×); recta y tramo sombreado; referencia de pendiente −1; mediana, IQR y mín–máx del control; caja con tramo, β̂ ± EE, Ĥ, R², RMSE, sensibilidad y Ĥ del control. Eje superior con m. |
| `robust_E1`, `robust_E2` | Var(tasa) en (B/s)² vs escala física para R1/R2 × Δ, y debajo la **pendiente local** entre escalas vecinas (−1 ↔ H = 0.5; 0 ↔ H = 1): es la mejor forma de ver si existe un tramo realmente lineal. |
| `H_summary` | Todas las Ĥ con su sensibilidad frente al rango y la mediana del control. |

Paleta: Okabe-Ito (A azul, B bermellón, A+B verde azulado), verificada para daltonismo. El color
nunca es la única pista: hay marcadores, estilos de línea, títulos de panel y leyenda.

## Cómo leer los resultados y qué artefactos vigilar

- **Referencia.** Datos independientes de varianza finita → V(m) ∝ 1/m (pendiente −1, H = 0.5).
  La banda gris del control debe seguir esa recta; si no, revisen la serie (p. ej. casi todo ceros).
- **E1 (tasa constante).** iperf3 espacia los datagramas casi regularmente, así que el número de
  paquetes por bloque oscila ±1 alrededor de la media. Eso hace que V(m) caiga *más rápido* que 1/m
  (pendiente cercana a −2) y Ĥ < 0.5: es **antipersistencia por regularidad**, no autosimilitud.
  Un Ĥ alto en E1 suele señalar un artefacto: caída de tasa, pausa del emisor, cambio de nivel
  (vean `trend_pct_per_100s`, `longest_silence_s` y `ts_*`).
- **E2 (ON/OFF programado).** Con ráfagas y pausas de 1–20 s, la varianza apenas disminuye en escalas
  menores que la duración típica de las ráfagas: la curva es casi plana y Ĥ ≈ 1 en 0.05–3 s, muy por
  encima del control. Pero eso refleja **el cronograma, no un escalamiento**: la pendiente local se
  empina hacia −1 al acercarse a la duración de los periodos (gráfica `robust_E2`) y la escala
  máxima medible (12.8 s con M ≥ 30) no alcanza a superar los periodos más largos (20 s). Con
  duraciones ON/OFF acotadas, a escalas mucho mayores se espera volver a H = 0.5. Contrastar Ĥ con el
  control demuestra **dependencia temporal**, pero no autosimilitud.
- **Ventana de 600 s.** Limita la escala útil: con Δ = 0.05 s, m = 256 (12.8 s) deja 46 bloques; con
  Δ = 0.10 s, ya no pasa el umbral de 30. Los silencios iniciales/finales de E2 entran en la serie y
  aumentan V(m) en escalas grandes; documenten cuánto duran (`activity_E2.csv`).
- **Δ = 0.05 vs 0.10 s.** Con el mismo t0 y N divisible, los bloques de 0.10 s son exactamente
  uniones de dos bloques de 0.05 s, así que **Var(tasa) coincide exactamente en las escalas físicas
  comunes** (`max_rel_diff_Vrate_common = 0`). Las diferencias de Ĥ entre Δ solo vienen del tramo
  elegido (Δ = 0.10 s pierde la escala de 0.05 s). Por eso la evidencia de robustez más fuerte es la
  concordancia **entre repeticiones** y la forma de la pendiente local; si quieren una prueba de la
  rejilla, desplacen t0 en Δ/2 con un `windows.csv` alternativo y comparen.
- **Sensibilidad.** Si |ΔĤ| al retirar una escala extrema es comparable a la distancia entre Ĥ y el
  control, la conclusión depende del tramo y debe reportarse como inconclusa.
- **Pérdidas y descartes.** Pérdidas UDP de red reducen tasa de forma aleatoria (efecto pequeño en
  V(m)); descartes del capturador pueden concentrarse en ráfagas y sesgar las escalas finas. Si hay
  descartes, repitan la corrida o acoten la conclusión.

Conclusión recomendada por escenario: "compatible con escalamiento de segundo orden en
[escala mín.–máx.] s", "sin ese patrón" o "inconcluso", con las figuras de pendiente local,
repeticiones y control como respaldo.
