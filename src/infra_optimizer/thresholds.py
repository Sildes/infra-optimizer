"""Seuils de détection — TOUTE la politique de détection centralisée ici.

Calibrage (exploration du dataset réel, 500 records / 10 jours) :
- baseline : CPU 52-63 %, latence 113-142 ms, error_rate 0.02, temp 57-63 °C ;
- pics : CPU 90-99, latence 315-384, error 0.11-0.13 — 49 occurrences ;
- la séparation baseline/pics est franche : un seuil à mi-chemin ne produit
  AUCUN faux positif sur cette série.

Sévérité :
- high   : impact service direct (latence, error_rate, service offline) ;
- medium : pression forte sans impact service prouvé (CPU, température) ;
- low    : signal à surveiller (saturation disque/mémoire, io_wait).
"""

CPU_HIGH = 85.0          # % — max baseline 63, min pics 90
CPU_CRITICAL = 90.0      # % — au-delà, sévérité high plutôt que medium
LATENCY_HIGH = 300.0     # ms — max baseline 142, min pics 315
ERROR_RATE_HIGH = 0.08   # — baseline 0.02, fenêtres dégradées 0.04-0.05, pics 0.11+
MEMORY_HIGH = 85.0       # %
DISK_HIGH = 85.0         # %
IO_WAIT_HIGH = 10.0      # %
TEMPERATURE_MEDIUM = 80.0  # °C — alerte thermique consécutive à la charge CPU

# Sévérité par état de service (anomalies de type service_status)
SERVICE_SEVERITY = {"offline": "high", "degraded": "medium"}