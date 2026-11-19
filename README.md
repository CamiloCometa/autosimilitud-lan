# Autosimilitud en trazas de tráfico LAN
Ivan Camilo-Francisco Morales
Entrega del taller "Autosimilitud en trazas de tráfico LAN": captura de tráfico UDP en una LAN de tres nodos
(**emulada**: network namespaces de Linux + bridge, como Mininet), estimación del parámetro de Hurst por
varianza agregada, control por 30 permutaciones, robustez (Δ = 0.10 s y dos repeticiones) y periodicidad.

**Informe (formato IEEE):** [`4_Informe/Informe_Autosimilitud_LAN.pdf`](4_Informe/Informe_Autosimilitud_LAN.pdf) · fuente LaTeX en [`4_Informe/latex/`](4_Informe/latex/)

## Resultado en una línea por escenario

| Escenario | Ĥ (tramo) | Control (30 permutaciones) | Conclusión |
|---|---|---|---|
| E1 · tasa constante | 0.03–0.05 (pendiente ≈ −1.9) | 0.49–0.51 | No muestra autosimilitud: tráfico antipersistente |
| E2 · ráfagas A y B | 0.97–0.98 en 0.05–3.2 s | 0.49–0.51 | Persistencia aparente por el cronograma ON/OFF; no compatible con autosimilitud en banda amplia |

## Contenido

| Carpeta | Entregable de la guía |
|---|---|
| `1_Montaje_y_adquisicion/` | Diagrama, comandos, versiones, ventanas (t0), cronogramas, pérdidas y registros de cada corrida |
| `2_Datos_y_codigo/` | Capturas PCAP, CSV exportados con TShark, código reproducible y `COMO_EJECUTAR.md` |
| `3_Graficas_y_tabla/` | 19 figuras (PNG 300 DPI + PDF), tablas (`summary.md`, `summary.csv`…) y `params.json` |
| `4_Informe/` | Informe en formato IEEE (PDF) y su fuente LaTeX (IEEEtran) |

`LISTA_DE_VERIFICACION.md` muestra que todos los elementos de la guía están presentes.

## Reproducir

```bash
cd 2_Datos_y_codigo
pip install -r codigo/requirements.txt
python codigo/run_analysis.py csv --windows ../1_Montaje_y_adquisicion/ventanas_windows.csv \
  --schedule ../1_Montaje_y_adquisicion/cronograma_schedule.csv \
  --meta ../1_Montaje_y_adquisicion/perdidas_y_descartes_runs.csv --out resultados
```

Con la semilla fija (20261118) los resultados coinciden con `3_Graficas_y_tabla/`.
