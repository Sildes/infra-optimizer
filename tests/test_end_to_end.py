"""Test de bout en bout : pipeline complet sur le dataset réel -> Report valide."""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from infra_optimizer.models import Report  # noqa: E402
from infra_optimizer.pipeline import run  # noqa: E402


def test_end_to_end_rapport_reel():
    p = Path(__file__).parent.parent.parent / "Test-Optimisation" / "rapport.json"
    if not p.exists():
        pytest.skip("rapport.json absent")
    report = run(p, use_llm=False)

    # Le Report EST la validation pydantic — impossible d'émettre non conforme.
    assert isinstance(report, Report)
    assert report.timestamp == "2023-10-11T21:30:00Z"   # dernier record trié
    assert len(report.anomalies) == 451
    assert len(report.recommendations) == 10
    assert report.insights.max_cpu_usage == 99.0

    # Sérialisation ronde : le JSON revalidé redonne le même rapport
    revalide = Report.model_validate_json(
        report.model_dump_json(indent=2)
    )
    assert revalide == report
