"""Nœud 3 — détection : anomalies par seuils métriques + états de service.

Deux familles de détecteurs, tous calibrés dans thresholds.py :

1. Métriques : un record qui dépasse un seuil produit une Anomaly.
   Les fenêtres CONSÉCUTIVES d'un même état de service sont agrégées en un
   seul événement (une dégradation de 6 records d'affilée = 1 anomalie, pas 6).

2. Services : un service non-online produit une anomalie de type
   service_status.<nom>.

Règle d'or anti-fausse-corrélation (piège du dataset) : les événements
`database offline` surviennent à charge NORMALE (CPU 57-63 % sur les 59
occurrences mesurées) — la détection reste PAR métrique, AUCUNE corrélation
automatique charge/statut n'est codée. L'interprétation appartient au nœud
de recommandation, sur la base de faits déjà détectés.
"""
import logging
from datetime import datetime, timedelta

from infra_optimizer import thresholds as th
from infra_optimizer.models import Anomaly, MetricRecord, ServiceStatusSummary

logger = logging.getLogger(__name__)

# Écart max entre deux records consécutifs pour prolonger une fenêtre :
# pas d'échantillonnage du dataset (30 min, mesuré sur les 499 écarts) + 1 min
# de marge pour absorber un léger jitter d'horodatage.
# Au-delà (trou de collecte), la fenêtre est fermée : on ne présume JAMAIS de
# la continuité d'un état non observé — un incident vu à travers un trou de
# données ressort comme deux événements, par choix explicite.
_GAP = timedelta(minutes=31)



def detect(records: list[MetricRecord]) -> tuple[list[Anomaly], ServiceStatusSummary]:
    """Retourne les anomalies détectées et le bilan des statuts de service."""
    # On initialise la liste des anomalies
    anomalies: list[Anomaly] = []

    for r in records:
        # On ajoute les anomalies métriques
        anomalies.extend(_metric_anomalies(r))

    # On ajoute les anomalies de service
    anomalies.extend(_service_anomalies(records))

    # On retourne les anomalies et le bilan des statuts de service
    return anomalies, _status_summary(records)


# ------------------------------------------------------------- métriques ----

def _metric_anomalies(r: MetricRecord) -> list[Anomaly]:
    """Retourne les anomalies métriques pour un record."""
    # On initialise la liste des anomalies
    out: list[Anomaly] = []

    # On ajoute les anomalies métriques
    if r.cpu_usage > th.CPU_HIGH:
        out.append(Anomaly( # On ajoute une anomalie pour la consommation CPU
            metric="cpu_usage",
            value=r.cpu_usage,
            threshold=th.CPU_HIGH,
            severity="high" if r.cpu_usage >= th.CPU_CRITICAL else "medium",
            description=f"CPU à {r.cpu_usage:.0f}% au {r.timestamp} (seuil {th.CPU_HIGH:.0f}%)",
        ))

    if r.latency_ms > th.LATENCY_HIGH:
        out.append(Anomaly( # On ajoute une anomalie pour la latence
            metric="latency_ms",
            value=r.latency_ms,
            threshold=th.LATENCY_HIGH,
            severity="high",
            description=f"Latence {r.latency_ms:.0f} ms au {r.timestamp} (seuil {th.LATENCY_HIGH:.0f} ms)",
        ))

    if r.error_rate > th.ERROR_RATE_HIGH:
        out.append(Anomaly( # On ajoute une anomalie pour le taux d'erreur
            metric="error_rate",
            value=r.error_rate,
            threshold=th.ERROR_RATE_HIGH,
            severity="high",
            description=f"Taux d'erreur {r.error_rate:.2f} au {r.timestamp} (seuil {th.ERROR_RATE_HIGH:.2f})",
        ))

    if r.temperature_celsius > th.TEMPERATURE_MEDIUM:
        out.append(Anomaly( # On ajoute une anomalie pour la température
            metric="temperature_celsius",
            value=r.temperature_celsius,
            threshold=th.TEMPERATURE_MEDIUM,
            severity="medium",
            description=f"Température {r.temperature_celsius:.0f}°C au {r.timestamp} (seuil {th.TEMPERATURE_MEDIUM:.0f}°C)",
        ))

    if r.memory_usage > th.MEMORY_HIGH:
        out.append(Anomaly( # On ajoute une anomalie pour la consommation mémoire
            metric="memory_usage", value=r.memory_usage, threshold=th.MEMORY_HIGH,
            severity="low",
            description=f"Mémoire {r.memory_usage:.0f}% au {r.timestamp} (seuil {th.MEMORY_HIGH:.0f}%)",
        ))

    if r.disk_usage > th.DISK_HIGH:
        out.append(Anomaly( # On ajoute une anomalie pour la consommation de disque
            metric="disk_usage", value=r.disk_usage, threshold=th.DISK_HIGH,
            severity="low",
            description=f"Disque {r.disk_usage:.0f}% au {r.timestamp} (seuil {th.DISK_HIGH:.0f}%)",
        ))

    if r.io_wait > th.IO_WAIT_HIGH:
        out.append(Anomaly( # On ajoute une anomalie pour l'attente IO
            metric="io_wait", value=r.io_wait, threshold=th.IO_WAIT_HIGH,
            severity="low",
            description=f"io_wait {r.io_wait:.0f} au {r.timestamp} (seuil {th.IO_WAIT_HIGH:.0f})",
        ))

    # On retourne la liste des anomalies
    return out


# -------------------------------------------------------------- services ----

def _ts(r: MetricRecord) -> datetime:
    return datetime.fromisoformat(r.timestamp.replace("Z", "+00:00"))


def _service_anomalies(records: list[MetricRecord]) -> list[Anomaly]:
    """Agrège les états non-online consécutifs d'un même service en un événement."""
    # On initialise la liste des anomalies
    anomalies: list[Anomaly] = []
    completed: list[tuple[str, str, dict]] = []
    # fenêtre en cours : (service, état) -> stats
    windows: dict[tuple[str, str], dict] = {}

    def _close(key, w):
        # On ajoute le service et l'état à la liste des services complets
        completed.append((key[0], key[1], w))

    for r in records:
        # clôturer les fenêtres dont le service est revenu online
        for key in [k for k in windows if k[0] in r.service_status and r.service_status[k[0]] == "online"]:
            _close(key, windows.pop(key)) # On ferme la fenêtre pour le service revenu online
        for svc, state in r.service_status.items(): # On parcourt les services et les états
            if state == "online": # Si le service est online, on continue
                continue
            key = (svc, state)
            w = windows.get(key) # On récupère la fenêtre pour le service et l'état
            if w and _ts(r) - w["last"] <= _GAP:
                w["last"] = _ts(r) # On met à jour la date de la dernière mesure
                w["count"] += 1 # On incrémente le nombre de mesures
                w["cpu"].append(r.cpu_usage)
            else: # Si la fenêtre n'existe pas ou si l'écart temporel est supérieur à _GAP  
                if w:  # Si la fenêtre existe, on ferme la fenêtre
                    _close(key, w)
                windows[key] = {"first": _ts(r), "last": _ts(r), "count": 1, "cpu": [r.cpu_usage]}

    # fenêtres encore ouvertes en fin de série
    for key, w in windows.items():
        _close(key, w) # On ferme la fenêtre pour le service et l'état

    for svc, state, w in completed: # On parcourt les services et les états
        anomalies.append(Anomaly( # On ajoute une anomalie pour le service et l'état
            metric=f"service_status.{svc}",
            value=float(w["count"]), # On ajoute le nombre de mesures
            # Un état de service n'a pas de seuil numérique : la règle est "au moins
            # 1 échantillon non-online déclenche l'anomalie" (contrat de l'énoncé rempli).
            threshold=1.0,
            severity=th.SERVICE_SEVERITY.get(state, "medium"), # On ajoute la gravité   
            description=(
                # On formate la date et l'heure en ISO 8601
                f"Service {svc} '{state}' du {w['first'].strftime('%Y-%m-%dT%H:%M:%SZ')} au "
                f"{w['last'].strftime('%Y-%m-%dT%H:%M:%SZ')} ({w['count']} échantillons, "
                f"CPU moyen {sum(w['cpu'])/len(w['cpu']):.0f}%)"

            ),
        ))
    # On retourne la liste des anomalies
    return anomalies


def _status_summary(records: list[MetricRecord]) -> ServiceStatusSummary:
    """Union historique dédupliquée des états observés sur la période."""
    # On initialise le dictionnaire des états
    seen: dict[str, set[str]] = {"online": set(), "degraded": set(), "offline": set()}
    for r in records: # On parcourt les records
        for svc, state in r.service_status.items():
            seen[state].add(svc)
    return ServiceStatusSummary( # On retourne le bilan des statuts de service
        online=sorted(seen["online"]),
        degraded=sorted(seen["degraded"]), # On ajoute les services en état degradé
        offline=sorted(seen["offline"]), # On ajoute les services en état offline
    )
