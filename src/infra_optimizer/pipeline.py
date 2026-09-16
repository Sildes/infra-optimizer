"""Orchestration du pipeline : ingestion -> analyse -> détection -> recommandation.

Chaque nœud est une fonction pure testable en isolation ; le pipeline les
compose séquentiellement. Pas de framework d'orchestration : un graphe
linéaire à 4 étapes aux contrats typés n'en a pas besoin (voir README,
section arbitrages).
"""
import argparse
import json
import logging
import sys
from pathlib import Path

from infra_optimizer.models import Report
from infra_optimizer.nodes.analysis import analyze
from infra_optimizer.nodes.detection import detect
from infra_optimizer.nodes.ingestion import ingest
from infra_optimizer.nodes.recommendation import recommend

logger = logging.getLogger(__name__)


def run(input_path: str | Path, use_llm: bool = True) -> Report:
    """Exécute le pipeline complet et retourne le rapport pydantic validé."""
    # On ingère les données
    records = ingest(input_path)
    logger.info("ingestion : %d records", len(records))

    # On analyse les données
    insights = analyze(records)
    logger.info("analyse : %d records agrégés en insights", len(records))

    # On détecte les anomalies
    anomalies, status_summary = detect(records)
    logger.info("détection : %d anomalies", len(anomalies))

    # On recommande les anomalies
    recommendations = recommend(anomalies, use_llm=use_llm)
    logger.info("recommandations : %d", len(recommendations))

    # On retourne le rapport
    return Report(
        timestamp=records[-1].timestamp,
        insights=insights,
        anomalies=anomalies,
        recommendations=recommendations,
        service_status_summary=status_summary,
    )


def main(argv: list[str] | None = None) -> int:
    # On crée le parser d'arguments
    parser = argparse.ArgumentParser(description="Analyse et optimisation d'infrastructure (test Devoteam)")
    parser.add_argument("--input", required=True, help="chemin du fichier de logs JSON")
    parser.add_argument("--output", default="output.json", help="chemin du rapport de sortie")
    # On ajoute l'argument pour activer ou désactiver le mode LLM
    parser.add_argument("--no-llm", action="store_true", help="force le mode déterministe (défaut si pas de clé)")
    parser.add_argument("-v", "--verbose", action="store_true")
    args = parser.parse_args(argv)

    # On configure le logging
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )

    # On exécute le pipeline
    report = run(args.input, use_llm=not args.no_llm)
    # On écrit le rapport dans le fichier spécifié
    Path(args.output).write_text(report.model_dump_json(indent=2))
    logger.info("rapport écrit : %s", args.output)
    return 0


if __name__ == "__main__":
    sys.exit(main())
