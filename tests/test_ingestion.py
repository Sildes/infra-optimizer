"""Tests du nœud ingestion — résilience, validation, tri.

Zéro dépendance réseau : le dataset réel n'est utilisé que via un chemin
fourni en variable d'environnement (facultatif) ; sinon données synthétiques.
"""
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from infra_optimizer.nodes.ingestion import ingest  # noqa: E402

# Record de référence complet et valide (baseline du dataset réel)
BASE_RECORD = {
    "timestamp": "2023-10-01T12:00:00Z",
    "cpu_usage": 56, "memory_usage": 64, "latency_ms": 132,
    "disk_usage": 60, "network_in_kbps": 1200, "network_out_kbps": 900,
    "io_wait": 2, "thread_count": 150, "active_connections": 50,
    "error_rate": 0.02, "uptime_seconds": 850000,
    "temperature_celsius": 60, "power_consumption_watts": 250,
    "service_status": {"database": "online", "api_gateway": "online", "cache": "online"},
}


def _tmp_json(tmp_path, data, name="t.json"):
    p = tmp_path / name
    p.write_text(json.dumps(data))
    return p


def test_rapport_reel_500_tri():
    """Golden test : le dataset réel passe intégralement, trié, 0 exclu."""
    rapport = Path(__file__).parent.parent.parent / "Test-Optimisation" / "rapport.json"
    if not rapport.exists():  # dataset non livré dans le dépôt -> CI légère
        pytest.skip("rapport.json absent")
    recs = ingest(rapport)
    assert len(recs) == 500
    ts = [r.timestamp for r in recs]
    assert ts == sorted(ts)
    assert recs[0].timestamp == "2023-10-01T12:00:00Z"
    assert recs[-1].timestamp == "2023-10-11T21:30:00Z"


def test_records_invalides_exclus(tmp_path):
    recs = ingest(
        _tmp_json(tmp_path, [dict(BASE_RECORD), {"timestamp": "X"}, "pasundict"])
    )
    assert len(recs) == 1


def test_timestamp_hors_format_rejete(tmp_path):
    """L'option ISO-UTC-stricte doit mordre : +02:00 = record invalide."""
    bad = dict(BASE_RECORD, timestamp="2023-10-01T14:00:00+02:00")
    recs = ingest(_tmp_json(tmp_path, [dict(BASE_RECORD), bad]))
    assert len(recs) == 1


def test_aucun_record_valide_valueerror(tmp_path):
    with pytest.raises(ValueError):
        ingest(_tmp_json(tmp_path, []))
