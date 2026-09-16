"""Tests du nœud recommendation — déterminisme, couverture, fallback LLM."""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from infra_optimizer.nodes.detection import detect  # noqa: E402
from infra_optimizer.nodes.ingestion import ingest  # noqa: E402
from infra_optimizer.nodes.recommendation import (  # noqa: E402
    BUILDERS,
    recommend,
)


def _anomalies_reelles():
    p = Path(__file__).parent.parent.parent / "Test-Optimisation" / "rapport.json"
    if not p.exists():
        pytest.skip("rapport.json absent")
    return detect(ingest(p))[0]


def test_une_reco_par_phenomene():
    """49 pics CPU = 1 reco scheduling, pas 49 lignes illisibles."""
    recs = recommend(_anomalies_reelles(), use_llm=False)
    assert len(recs) == 10
    ids = [r.id for r in recs]
    assert "investigate-recurring-cpu-spikes" in ids
    assert "database-stability" in ids


def test_aucune_anomalie_orpheline():
    """Chaque métrique détectée a sa reco (memory/disk/io_wait inclus)."""
    anomalies = _anomalies_reelles()
    recs = recommend(anomalies, use_llm=False)
    metrics_detectees = {a.metric for a in anomalies}
    assert metrics_detectees <= set(BUILDERS)
    assert len(recs) == len(metrics_detectees)


def test_reco_database_ne_dit_pas_scaler():
    """Le piège du dataset : jamais 'scale la base' — stabilité, pas capacité."""
    recs = recommend(_anomalies_reelles(), use_llm=False)
    db = next(r for r in recs if r.id == "database-stability")
    assert "charge NORMALE" in db.action


def test_fallback_llm_sans_cle(monkeypatch):
    """Sans LLM_API_KEY : use_llm=True = strictement les templates."""
    monkeypatch.delenv("LLM_API_KEY", raising=False)
    anomalies = _anomalies_reelles()
    assert recommend(anomalies, use_llm=True) == recommend(anomalies, use_llm=False)


def test_fallback_llm_erreur_reseau(monkeypatch):
    """Avec clé mais API injoignable : repli silencieux, rapport quand même."""
    monkeypatch.setenv("LLM_API_KEY", "fake")
    monkeypatch.setenv("LLM_BASE_URL", "http://127.0.0.1:1")  # rien n'écoute
    anomalies = _anomalies_reelles()
    assert recommend(anomalies, use_llm=True) == recommend(anomalies, use_llm=False)
