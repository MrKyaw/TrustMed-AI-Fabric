from datetime import UTC, datetime

from trustmed_fabric.evals import load_cases, run_evaluations


def test_eval_gate_passes(service) -> None:
    thresholds, cases = load_cases()
    report = run_evaluations(service.assistant, as_of=datetime(2026, 6, 15, tzinfo=UTC), cases=cases[:5], thresholds=thresholds)
    assert report.metrics.total == 5
    assert report.gate_passed is True


def test_eval_full_gate_passes(service, tmp_path) -> None:
    report, json_path, md_path = service.refresh_eval_report()
    assert report.gate_passed is True
    assert report.metrics.pass_rate == 1.0
    assert report.metrics.citation_validity == 1.0
    assert report.metrics.refusal_accuracy == 1.0
    assert report.metrics.retrieval_recall_at_3 == 1.0
    assert report.metrics.groundedness == 1.0
    assert json_path.exists()
    assert md_path.exists()
    assert "PASS" in md_path.read_text()
