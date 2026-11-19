# Cómo reproducir el análisis

Desde esta carpeta (`2_Datos_y_codigo`), con Python 3.9+:

```
pip install -r codigo/requirements.txt
python codigo/run_analysis.py csv --windows ../1_Montaje_y_adquisicion/ventanas_windows.csv --schedule ../1_Montaje_y_adquisicion/cronograma_schedule.csv --meta ../1_Montaje_y_adquisicion/perdidas_y_descartes_runs.csv --out resultados
```

O con doble clic en `codigo/Iniciar.bat` (Windows) y eligiendo la carpeta `csv` en la ventana.
Los resultados deben coincidir con `3_Graficas_y_tabla` (semilla fija 20261118).
