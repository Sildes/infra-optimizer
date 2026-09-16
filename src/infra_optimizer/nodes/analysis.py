"""Nœud 2 — analyse : agrégats de la période (bloc insights du rapport)."""
from statistics import mean

from infra_optimizer.models import Insights, MetricRecord


def analyze(records: list[MetricRecord]) -> Insights:
    """Calcule les insights exigés par l'énoncé sur la série complète.

    Décisions documentées (voir models.Insights) :
    - error_rate = moyenne de la période ;
    - uptime_seconds = dernière valeur (gauge monotone).
    """
    # On vérifie que la liste de records n'est pas vide
    if not records:
        raise ValueError("analyse impossible : liste de records vide")

    # On calcule les insights
    insights = Insights(
        # On calcule la moyenne de la latence
        average_latency_ms=mean(r.latency_ms for r in records),
        # On calcule le max de la consommation CPU
        max_cpu_usage=max(r.cpu_usage for r in records),
        # On calcule le max de la consommation mémoire
        max_memory_usage=max(r.memory_usage for r in records),
        # Moyenne (et non médiane) : les incidents doivent rester visibles
        # dans les agrégats — la médiane (0.02, baseline) masquerait la
        # dégradation causée par les ~83 records déviants.
        error_rate=mean(r.error_rate for r in records),

        # uptime est un compteur cumulatif :
        # la moyenne n'a aucun sens, on prend la dernière valeur (état actuel).
        uptime_seconds=records[-1].uptime_seconds,
    )
    return insights