"""
Parámetros del laboratorio "Autosimilitud en trazas de tráfico LAN".

Todo lo que define el experimento (direcciones, puertos, ventana, escalas,
criterios de ajuste, semilla) vive aquí para que el análisis sea reproducible
y auditable. La CLI (run_analysis.py) puede sobrescribir algunos campos.
"""
from __future__ import annotations

from dataclasses import dataclass, field, asdict
from typing import Optional, Tuple

# --------------------------------------------------------------------------
# Topología (sección 1 del taller)
# --------------------------------------------------------------------------
SERVER_IP = "192.168.50.13"          # Nodo C (captura + servidores iperf3)

# Fuente -> (IP origen, puerto UDP destino)
SOURCES = {
    "A": ("192.168.50.11", 5201),
    "B": ("192.168.50.12", 5202),
}

# Series que se analizan en cada escenario. La primera es la "serie principal".
SCENARIO_SERIES = {
    "E1": ("A",),                 # tráfico constante, solo A
    "E2": ("A+B", "A", "B"),      # agregado + individuales, mismo t0
}


@dataclass(frozen=True)
class AnalysisConfig:
    # ---- ventana y resolución -------------------------------------------
    window_s: float = 600.0                       # duración de la ventana
    base_delta_s: float = 0.05                    # Δ principal
    robust_delta_s: float = 0.10                  # Δ de robustez
    scales: Tuple[int, ...] = (1, 2, 4, 8, 16, 32, 64, 128, 256)

    # ---- criterios de ajuste --------------------------------------------
    min_blocks: int = 30                          # M_m mínimo para usar la escala
    min_fit_scales: int = 4                       # escalas consecutivas mínimas
    max_rmse_dex: float = 0.03                    # RMSE máx. de residuos (log10 V)
    max_local_slope_dev: float = 0.20             # |pendiente local - β| máx.
    r2_min: Optional[float] = None                # umbral R² opcional (ver hurst.py)
    # Rango físico forzado (s) para el tramo, p. ej. (0.1, 6.4). None = automático
    fit_range_s: Optional[Tuple[float, float]] = None

    # ---- control por permutación ----------------------------------------
    n_perm: int = 30
    seed: int = 20261118                          # semilla base documentada

    # ---- gráficas temporales --------------------------------------------
    ts_resolutions_s: Tuple[float, ...] = (0.05, 0.4, 3.2)
    on_gap_merge_s: float = 0.5                   # une silencios < este valor al
                                                  # detectar ráfagas ON en E2
    # Referencia nominal opcional en bytes/s de trama (None = no dibujar).
    # iperf3 -b 4M -l 1200 -> 416.7 datagramas/s; con 42 B de cabeceras
    # Ethernet+IP+UDP la tasa de trama es ≈ 416.7 * 1242 ≈ 517 500 B/s.
    nominal_frame_rate_Bps: Optional[float] = 4e6 / (1200 * 8) * 1242

    # ---- salida ----------------------------------------------------------
    dpi: int = 300
    formats: Tuple[str, ...] = ("png", "pdf")

    @property
    def deltas(self) -> Tuple[float, float]:
        return (self.base_delta_s, self.robust_delta_s)

    def as_dict(self) -> dict:
        d = asdict(self)
        d["deltas"] = list(self.deltas)
        return d
