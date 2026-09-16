"""Nœud 1 — ingestion : lecture, validation, tri chronologique."""
import json
import logging
from pathlib import Path

from infra_optimizer.models import MetricRecord

logger = logging.getLogger(__name__)

def ingest(path: str | Path) -> list[MetricRecord]:
    """Charge le fichier de logs JSON, valide chaque record, trie par timestamp.

    Résilience : un record invalide est EXCLU et journalisé — le pipeline
    continue sur les données saines, rien n'échoue en cascade.
    """
    raw_records = json.loads(Path(path).read_text())

    records: list[MetricRecord] = []
    excluded = 0
    for i, raw in enumerate(raw_records):
        try:
            records.append(MetricRecord(**raw))
        except Exception:
            excluded += 1
            logger.warning("record %d invalide, exclu (ts=%s)", i, raw.get("timestamp", "?") if isinstance(raw, dict) else raw)

    if excluded:
        logger.info("ingestion : %d/%d records exclus", excluded, len(raw_records))
    if not records:
        raise ValueError(f"aucun record valide dans {path}")

    # On trie les records par timestamp, qui ont une contrainte de validation définie dans models.py
    records.sort(key=lambda r: r.timestamp)
    return records