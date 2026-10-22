"""Golden-set evaluation harness and CI quality gate.

The harness evaluates the same public assistant that the API and MCP tools
expose. It checks refusals, retrieval, citations, grounding, latency and the
policy decision attached to each answer, then renders a human-readable report.
"""

from __future__ import annotations

import json
import math
from datetime import datetime
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field

from trustmed_fabric.assistant import GovernedAssistant
from trustmed_fabric.fixtures import eval_pack
from trustmed_fabric.models import AskRequest, Audience, Channel, Market
from trustmed_fabric.timeutil import ensure_utc, utcnow


class EvalThresholds(BaseModel):
    pass_rate: float
    citation_validity: float
    refusal_accuracy: float
    retrieval_recall_at_3: float
    groundedness: float


class EvalCase(BaseModel):
    id: str
    question: str
    market: Market
    audience: Audience
    channel: Channel | None = None
    expect_refusal: bool
    required_reason: str | None = None
    expected_asset_ids: list[str] = Field(default_factory=list)
    must_include_terms: list[str] = Field(default_factory=list)
    forbidden_terms: list[str] = Field(default_factory=list)


class EvalCaseResult(BaseModel):
    id: str
    question: str
    passed: bool
    expected_refusal: bool
    refused: bool
    refusal_reason: str | None
    citation_ids: list[str]
    cited_asset_ids: list[str]
    latency_ms: float
    grounding_score: float
    failure_reasons: list[str]


class EvalMetrics(BaseModel):
    total: int
    passed: int
    pass_rate: float
    citation_validity: float
    refusal_accuracy: float
    retrieval_recall_at_3: float
    groundedness: float
    p95_latency_ms: float


class EvalReport(BaseModel):
    version: str
    generated_at: datetime
    as_of: datetime
    model: str
    thresholds: EvalThresholds
    metrics: EvalMetrics
    gate_passed: bool
    cases: list[EvalCaseResult]


def load_cases() -> tuple[EvalThresholds, list[EvalCase]]:
    pack = eval_pack()
    thresholds = EvalThresholds.model_validate(pack["thresholds"])
    cases = [EvalCase.model_validate(item) for item in pack["cases"]]
    return thresholds, cases


def run_evaluations(
    assistant: GovernedAssistant,
    *,
    as_of: datetime | None = None,
    cases: list[EvalCase] | None = None,
    thresholds: EvalThresholds | None = None,
) -> EvalReport:
    loaded_thresholds, loaded_cases = load_cases()
    threshold_model = thresholds or loaded_thresholds
    case_list = cases or loaded_cases
    run_at = ensure_utc(as_of or utcnow())
    results: list[EvalCaseResult] = []
    citation_checks: list[bool] = []
    refusal_checks: list[bool] = []
    recall_checks: list[float] = []
    grounding_scores: list[float] = []
    latencies: list[float] = []

    for case in case_list:
        response = assistant.ask(
            AskRequest(
                question=case.question,
                market=case.market,
                audience=case.audience,
                channel=case.channel,
                as_of=run_at,
            ),
            now=run_at,
        )
        failures: list[str] = []
        if case.expect_refusal:
            if not response.refused:
                failures.append("expected a refusal but received an answer")
            if case.required_reason and response.refusal_reason != case.required_reason:
                failures.append(
                    f"expected refusal reason {case.required_reason}, "
                    f"received {response.refusal_reason}"
                )
            refusal_checks.append(not failures)
        else:
            if response.refused:
                failures.append(f"unexpected refusal: {response.refusal_reason}")
            lowered = response.answer.lower()
            for term in case.must_include_terms:
                if term.lower() not in lowered:
                    failures.append(f"answer missing required term {term!r}")
            for term in case.forbidden_terms:
                if term.lower() in lowered:
                    failures.append(f"answer contains forbidden term {term!r}")
            cited = [citation.asset_id for citation in response.citations]
            if not cited:
                failures.append("answer has no citations")
            if case.expected_asset_ids and not set(cited).intersection(case.expected_asset_ids):
                failures.append(
                    f"expected one of {case.expected_asset_ids}, cited {sorted(set(cited))}"
                )
            if case.expected_asset_ids:
                recall_checks.append(
                    1.0
                    if set(cited).intersection(case.expected_asset_ids)
                    else 0.0
                )
            else:
                recall_checks.append(1.0)
            valid = all(
                citation.expires_at >= run_at and citation.asset_version >= 1
                for citation in response.citations
            )
            citation_checks.append(valid and bool(response.citations))
            grounding = float(response.retrieval_meta.get("grounding_score", 0.0))
            grounding_scores.append(grounding)
            if grounding < 0.85:
                failures.append(f"grounding below 0.85 ({grounding:.2f})")
        latency = response.latency_ms
        latencies.append(latency)
        if latency > 5000:
            failures.append(f"latency {latency:.0f}ms exceeds 5000ms")
        results.append(
            EvalCaseResult(
                id=case.id,
                question=case.question,
                passed=not failures,
                expected_refusal=case.expect_refusal,
                refused=response.refused,
                refusal_reason=response.refusal_reason,
                citation_ids=[c.citation_id for c in response.citations],
                cited_asset_ids=sorted({c.asset_id for c in response.citations}),
                latency_ms=latency,
                grounding_score=float(response.retrieval_meta.get("grounding_score", 1.0)),
                failure_reasons=failures,
            )
        )

    passed = sum(1 for result in results if result.passed)
    pass_rate = passed / len(results) if results else 0.0
    citation_validity = (
        sum(1 for value in citation_checks if value) / len(citation_checks)
        if citation_checks
        else 1.0
    )
    refusal_accuracy = (
        sum(1 for value in refusal_checks if value) / len(refusal_checks)
        if refusal_checks
        else 1.0
    )
    recall = sum(recall_checks) / len(recall_checks) if recall_checks else 1.0
    groundedness = (
        sum(grounding_scores) / len(grounding_scores) if grounding_scores else 1.0
    )
    p95 = _percentile(latencies, 0.95)
    metrics = EvalMetrics(
        total=len(results),
        passed=passed,
        pass_rate=round(pass_rate, 4),
        citation_validity=round(citation_validity, 4),
        refusal_accuracy=round(refusal_accuracy, 4),
        retrieval_recall_at_3=round(recall, 4),
        groundedness=round(groundedness, 4),
        p95_latency_ms=round(p95, 3),
    )
    gate = (
        metrics.pass_rate >= threshold_model.pass_rate
        and metrics.citation_validity >= threshold_model.citation_validity
        and metrics.refusal_accuracy >= threshold_model.refusal_accuracy
        and metrics.retrieval_recall_at_3 >= threshold_model.retrieval_recall_at_3
        and metrics.groundedness >= threshold_model.groundedness
    )
    return EvalReport(
        version=str(eval_pack().get("version", "1")),
        generated_at=utcnow(),
        as_of=run_at,
        model=response.model if case_list else "deterministic-extractive-v1",
        thresholds=threshold_model,
        metrics=metrics,
        gate_passed=gate,
        cases=results,
    )


def _percentile(values: list[float], percentile: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    index = max(0, math.ceil(percentile * len(ordered)) - 1)
    return ordered[index]


def render_markdown(report: EvalReport) -> str:
    status = "PASS" if report.gate_passed else "FAIL"
    lines = [
        "# Evaluation Report",
        "",
        f"**Quality gate:** `{status}`",
        "",
        f"- Generated: `{report.generated_at.isoformat()}`",
        f"- Evaluation clock: `{report.as_of.isoformat()}`",
        f"- Model: `{report.model}`",
        f"- Golden cases: **{report.metrics.passed}/{report.metrics.total} passing**",
        "",
        "## Metrics",
        "",
        "| Metric | Result | Threshold | Status |",
        "| --- | ---: | ---: | :---: |",
        _metric_row("Case pass rate", report.metrics.pass_rate, report.thresholds.pass_rate),
        _metric_row(
            "Citation validity",
            report.metrics.citation_validity,
            report.thresholds.citation_validity,
        ),
        _metric_row(
            "Refusal accuracy",
            report.metrics.refusal_accuracy,
            report.thresholds.refusal_accuracy,
        ),
        _metric_row(
            "Retrieval recall@3",
            report.metrics.retrieval_recall_at_3,
            report.thresholds.retrieval_recall_at_3,
        ),
        _metric_row(
            "Groundedness", report.metrics.groundedness, report.thresholds.groundedness
        ),
        "",
        f"P95 latency: **{report.metrics.p95_latency_ms:.1f} ms** (in-process, deterministic).",
        "",
        "## Cases",
        "",
        "| Case | Question | Expected | Result | Citations | Grounding |",
        "| --- | --- | --- | :---: | --- | ---: |",
    ]
    for case in report.cases:
        expected = "refuse" if case.expected_refusal else "answer"
        citations = ", ".join(case.cited_asset_ids) or "-"
        lines.append(
            f"| {case.id} | {_escape(case.question)} | {expected} | "
            f"{'PASS' if case.passed else 'FAIL'} | {citations} | "
            f"{case.grounding_score:.2f} |"
        )
    failed = [case for case in report.cases if not case.passed]
    lines.extend(["", "## Failures", ""])
    if not failed:
        lines.append("No failures. Every golden case passed every assertion.")
    else:
        for case in failed:
            lines.append(f"- **{case.id}**: " + "; ".join(case.failure_reasons))
    lines.append("")
    return "\n".join(lines)


def _metric_row(name: str, value: float, threshold: float) -> str:
    status = "PASS" if value >= threshold else "FAIL"
    return f"| {name} | {value:.3f} | {threshold:.3f} | {status} |"


def _escape(value: str) -> str:
    return value.replace("|", "\\|")


def write_reports(report: EvalReport, directory: str | Path) -> tuple[Path, Path]:
    target = Path(directory)
    target.mkdir(parents=True, exist_ok=True)
    json_path = target / "eval-report.json"
    md_path = target / "eval-report.md"
    json_path.write_text(
        json.dumps(report.model_dump(mode="json"), indent=2) + "\n", encoding="utf-8"
    )
    md_path.write_text(render_markdown(report), encoding="utf-8")
    return json_path, md_path


def load_report(path: str | Path) -> EvalReport | None:
    file = Path(path)
    if not file.exists():
        return None
    try:
        return EvalReport.model_validate_json(file.read_text(encoding="utf-8"))
    except (ValueError, OSError):
        return None


def report_summary(report: EvalReport) -> dict[str, Any]:
    return report.model_dump(mode="json")
