"""Tests du nœud analysis — valeurs attendues sur le dataset réel."""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from infra_optimizer.nodes.analysis import analyze  # noqa: E402
from infra_optimizer.nodes.ingestion import ingest  # noqa: E402


def _rapport():
    p = Path(__file__).parent.parent.parent / "Test-Optimisation" / "rapport.json"
    if not p.exists():
        pytest.skip("rapport.json absent")
    return ingest(p)


def test_valeurs_attendues():
    """Chiffres recalculés indépendamment depuis le JSON brut."""
    recs = _rapport()
    ins = analyze(recs)
    assert ins.average_latency_ms == 156.018
    assert ins.max_cpu_usage == 99.0
    assert ins.max_memory_usage == 92.0
    assert round(ins.error_rate, 5) == 0.03158
    # compteur cumulatif : la DERNIÈRE valeur de la série triée
    assert ins.uptime_seconds == 1258200.0


def test_liste_vide_valueerror():
    with pytest.raises(ValueError):
        analyze([])
