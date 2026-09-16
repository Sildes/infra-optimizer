"""Tests du nœud detection — comptages, agrégation de fenêtres, pièges."""
import re
import sys
from collections import Counter
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from infra_optimizer.nodes.detection import detect  # noqa: E402
from infra_optimizer.nodes.ingestion import ingest  # noqa: E402


def _detect_reel():
    p = Path(__file__).parent.parent.parent / "Test-Optimisation" / "rapport.json"
    if not p.exists():
        pytest.skip("rapport.json absent")
    return detect(ingest(p))


def test_comptages_attendus():
    anomalies, _ = _detect_reel()
    c = Counter(a.metric for a in anomalies)
    assert c["cpu_usage"] == 49        # les 49 pics mesurés
    assert c["latency_ms"] == 49       # zéro faux positif baseline (max 142 < 300)
    assert c["error_rate"] == 49
    assert c["service_status.database"] == 59


def test_severite_cpu_tous_high():
    """Pics mesurés 90-99 -> règle >= CPU_CRITICAL : 49/49 high."""
    anomalies, _ = _detect_reel()
    cpu = [a for a in anomalies if a.metric == "cpu_usage"]
    assert len(cpu) == 49
    assert all(a.severity == "high" for a in cpu)


def test_fenetres_agregees():
    """6 échantillons consécutifs = 1 événement, pas 6."""
    anomalies, _ = _detect_reel()
    six = [a for a in anomalies if "6 échantillons" in a.description]
    assert len(six) >= 5  # 3 journées x api_gateway + cache


def test_piege_database_non_correlee():
    """Les 59 'database offline' sont à charge NORMALE — jamais > 70% CPU."""
    anomalies, _ = _detect_reel()
    db = [a for a in anomalies if a.metric == "service_status.database"]
    assert len(db) == 59
    for a in db:
        m = re.search(r"CPU moyen (\d+)", a.description)
        assert m and int(m.group(1)) <= 70, a.description


def test_format_z_descriptions():
    """Convention UTC suffixe Z partout, y compris dans les descriptions."""
    anomalies, _ = _detect_reel()
    svc = [a for a in anomalies if a.metric.startswith("service_status.")]
    assert svc
    for a in svc:
        assert "+00:00" not in a.description, a.description


def test_summary_statuts():
    _, summary = _detect_reel()
    assert summary.model_dump() == {
        "online": ["api_gateway", "cache", "database"],
        "degraded": ["api_gateway", "cache"],
        "offline": ["database"],
    }
