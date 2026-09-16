"""Nœud 4 — recommandations : actions concrètes à partir des anomalies détectées.

Deux modes, le déterministe est le DÉFAUT :

1. Templates déterministes : chaque type d'anomalie -> une recommandation
   enrichie des chiffres réels mesurés par la détection. Reproductible,
   testable, sans réseau — le rapport est générable en CI sans clé API.

2. Mode LLM (optionnel, si LLM_API_KEY est définie) : UN appel, le LLM
   reçoit le RÉSUMÉ des anomalies détectées (jamais les données brutes) et
   rédige les recommandations. Sa sortie est validée par pydantic ; en cas
   d'échec, timeout ou sortie invalide : repli silencieux sur les templates.
   Le LLM AMÉLIORE la formulation, il ne crée pas les faits.
"""
import logging
import os
from collections.abc import Callable

from infra_optimizer.models import Anomaly, Recommendation

logger = logging.getLogger(__name__)

Builder = Callable[[list[Anomaly]], Recommendation]


def recommend(anomalies: list[Anomaly], use_llm: bool = True) -> list[Recommendation]:
    """Produit les recommandations depuis les anomalies (déterministe + LLM optionnel)."""
    recs = _deterministic(anomalies)

    if use_llm and os.environ.get("LLM_API_KEY"):
        try:
            recs = _llm_polish(anomalies, recs)
        except Exception as e:  # noqa: BLE001 — le LLM est un bonus, jamais un risque
            logger.warning("mode LLM échoué (%s), repli sur templates", e)

    return recs


# --------------------------------------------------------- déterministe ----

def _rec_cpu(anomalies: list[Anomaly]) -> Recommendation:
    n = len(anomalies)
    worst = max(a.value for a in anomalies)
    return Recommendation(
        id="investigate-recurring-cpu-spikes",
        action=(
            f"Investiguer le pattern de charge récurrent ({n} pics CPU sur la période, "
            f"max {worst:.0f}%) : identifier le scheduling (batch/cron) à l'origine et "
            "décaler ou lisser les traitements"
        ),
        target="serveur",
        parameters={"spike_count": n, "observed_max": worst, "threshold": anomalies[0].threshold},
        benefit_estimate="Suppression des pics de latence et des erreurs associées",
    )


def _rec_latency(anomalies: list[Anomaly]) -> Recommendation:
    return Recommendation(
        id="api-gateway-autoscaling",
        action=(
            "Mettre en place l'autoscaling / la répartition de charge sur l'API gateway "
            "et réduire la latence (cache des réponses, CDN)"
        ),
        target="api_gateway",
        parameters={"occurrences": len(anomalies), "max_latency_ms": max(a.value for a in anomalies)},
        benefit_estimate="Latence ramenée sous 150 ms même en pic",
    )


def _rec_error(anomalies: list[Anomaly]) -> Recommendation:
    return Recommendation(
        id="alerting-error-rate",
        action="Ajouter une alerte sur error_rate > 0.08 avec corrélation aux déploiements",
        target="monitoring",
        parameters={"occurrences": len(anomalies), "max": max(a.value for a in anomalies)},
        benefit_estimate="Détection précoce des phases de surcharge",
    )


def _rec_temp(anomalies: list[Anomaly]) -> Recommendation:
    return Recommendation(
        id="thermal-headroom",
        action="Vérifier le refroidissement et la capacité thermique (températures > 80°C pendant les pics)",
        target="serveur",
        parameters={"occurrences": len(anomalies), "max_celsius": max(a.value for a in anomalies)},
        benefit_estimate="Prévention de la throttling CPU et de l'usure matériel",
    )


def _rec_memory(anomalies: list[Anomaly]) -> Recommendation:
    return Recommendation(
        id="memory-headroom",
        action=(
            f"Auditer l'usage mémoire : {len(anomalies)} dépassement(s) observés — "
            "vérifier les fuites (processus à croissance continue) et le headroom"
        ),
        target="serveur",
        parameters={"occurrences": len(anomalies), "max_percent": max(a.value for a in anomalies)},
        benefit_estimate="Prévention de l'OOM kill et de la dégradation en pic",
    )


def _rec_disk(anomalies: list[Anomaly]) -> Recommendation:
    return Recommendation(
        id="disk-capacity-planning",
        action=(
            f"Planifier la capacité disque : {len(anomalies)} relevé(s) au-delà du seuil, "
            "max mesuré à {m:.0f}% — purger/archiver avant saturation".format(
                m=max(a.value for a in anomalies)
            )
        ),
        target="serveur",
        parameters={"occurrences": len(anomalies), "max_percent": max(a.value for a in anomalies)},
        benefit_estimate="Évite la panne sèche de service liée au disque plein",
    )


def _rec_io_wait(anomalies: list[Anomaly]) -> Recommendation:
    return Recommendation(
        id="io-subsystem-investigation",
        action=(
            f"Investiguer le sous-système disque : {len(anomalies)} relevé(s) d'io_wait élevé, "
            "corrélés aux pics de charge — vérifier IOPS, répartition des disques (RAID) et cache disque"
        ),
        target="serveur",
        parameters={"occurrences": len(anomalies), "max_percent": max(a.value for a in anomalies)},
        benefit_estimate="Réduction de l'attente I/O pendant les pics",
    )


def _rec_svc(svc: str, anomalies: list[Anomaly]) -> Recommendation:
    return Recommendation(
        id=f"{svc}-stability",
        action=(
            f"Analyser la stabilité du service {svc} : {len(anomalies)} fenêtre(s) de dégradation "
            "observées, dont certaines à charge moyenne — investiguer capacité et éviction"
        ),
        target=svc,
        parameters={"windows": len(anomalies)},
        benefit_estimate="Disponibilité du service en continu",
    )


def _rec_db(anomalies: list[Anomaly]) -> Recommendation:
    return Recommendation(
        id="database-stability",
        action=(
            f"Vérifier la stabilité de la database : {len(anomalies)} interruption(s) observée(s) à charge "
            "NORMALE (sans corrélation avec les pics CPU) — investiguer côté DB (maintenance, "
            "timeouts, redémarrages), pas un problème de capacité"
        ),
        target="database",
        parameters={"interruptions": len(anomalies)},
        benefit_estimate="Suppression des micro-coupures base de données",
    )


BUILDERS: dict[str, Builder] = {
    "cpu_usage": _rec_cpu,
    "latency_ms": _rec_latency,
    "memory_usage": _rec_memory,
    "disk_usage": _rec_disk,
    "io_wait": _rec_io_wait,
    "error_rate": _rec_error,
    "temperature_celsius": _rec_temp,
    "service_status.api_gateway": lambda a: _rec_svc("api_gateway", a),
    "service_status.cache": lambda a: _rec_svc("cache", a),
    "service_status.database": _rec_db,
}


def _deterministic(anomalies: list[Anomaly]) -> list[Recommendation]:
    by_metric: dict[str, list[Anomaly]] = {}
    for a in anomalies:
        by_metric.setdefault(a.metric, []).append(a)

    return [
        builder(items)
        for metric, builder in BUILDERS.items()
        if (items := by_metric.get(metric))
    ]


# ------------------------------------------------------------------ llm ----

def _llm_polish(anomalies: list[Anomaly], fallback: list[Recommendation]) -> list[Recommendation]:
    """Réécrit les recommandations via LLM ; sortie validée pydantic sinon repli.

    Contrat : le modèle reçoit anomalies + recommandations templates et ne
    peut ni inventer de faits, ni changer les paramètres mesurés.
    """
    from infra_optimizer.llm import rewrite_recommendations  # import tardif : zéro dépendance au module sans clé

    polished = rewrite_recommendations(anomalies, fallback)
    if not polished:  # sortie vide ou invalide -> templates
        return fallback
    return polished
