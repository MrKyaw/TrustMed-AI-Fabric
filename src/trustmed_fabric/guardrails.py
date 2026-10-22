"""Input and output guardrails for the governed assistant."""

from __future__ import annotations

import re
from dataclasses import dataclass

from trustmed_fabric.language import (
    asks_for_clinical_advice,
    contains_injection,
    find_pii,
    find_prohibited,
    references_unapproved_content,
)
from trustmed_fabric.models import GuardrailCheck, RetrievedPassage, Severity
from trustmed_fabric.retrieval import SENTENCE_RE, tokenize

CITATION_MARKER = re.compile(r"\[\d+\]")


@dataclass
class InputScreen:
    reason: str | None
    checks: list[GuardrailCheck]


def screen_input(question: str) -> InputScreen:
    checks: list[GuardrailCheck] = []
    injection = contains_injection(question)
    checks.append(
        GuardrailCheck(
            id="INPUT-INJECTION",
            passed=not injection,
            message=(
                "Instruction-override pattern detected"
                if injection
                else "No instruction-override pattern detected"
            ),
            severity=Severity.BLOCKER if injection else Severity.INFO,
        )
    )
    pii = find_pii(question)
    checks.append(
        GuardrailCheck(
            id="INPUT-PII",
            passed=not pii,
            message=(
                f"Personal data detected ({', '.join(pii)}); remove it before asking"
                if pii
                else "No personal data detected"
            ),
            severity=Severity.BLOCKER if pii else Severity.INFO,
        )
    )
    prohibited = find_prohibited(question)
    checks.append(
        GuardrailCheck(
            id="INPUT-PROHIBITED-FRAMING",
            passed=not prohibited,
            message=(
                "Question contains absolute or curative framing"
                if prohibited
                else "No absolute or curative framing detected"
            ),
            severity=Severity.BLOCKER if prohibited else Severity.INFO,
        )
    )
    clinical = asks_for_clinical_advice(question)
    checks.append(
        GuardrailCheck(
            id="INPUT-CLINICAL-ADVICE",
            passed=not clinical,
            message=(
                "The assistant does not provide prescribing or treatment advice"
                if clinical
                else "No request for clinical advice detected"
            ),
            severity=Severity.BLOCKER if clinical else Severity.INFO,
        )
    )
    unapproved = references_unapproved_content(question)
    checks.append(
        GuardrailCheck(
            id="INPUT-UNAPPROVED-REFERENCE",
            passed=not unapproved,
            message=(
                "Question asks about unapproved or withdrawn content"
                if unapproved
                else "No reference to unapproved content"
            ),
            severity=Severity.BLOCKER if unapproved else Severity.INFO,
        )
    )

    reason: str | None = None
    if injection:
        reason = "PROMPT_INJECTION"
    elif pii:
        reason = "PII_IN_INPUT"
    elif prohibited:
        reason = "PROHIBITED_FRAMING"
    elif clinical:
        reason = "CLINICAL_ADVICE"
    elif unapproved:
        reason = "UNAPPROVED_REFERENCE"
    return InputScreen(reason=reason, checks=checks)


def verify_answer(
    answer: str, passages: list[RetrievedPassage], citation_ids: list[str]
) -> tuple[list[GuardrailCheck], float, bool]:
    checks: list[GuardrailCheck] = []
    has_citations = bool(citation_ids) and all(f"[{i}]" in answer for i in range(1, len(citation_ids) + 1))
    checks.append(
        GuardrailCheck(
            id="OUTPUT-CITATIONS",
            passed=has_citations,
            message=(
                f"{len(citation_ids)} approved source(s) cited in the answer"
                if has_citations
                else "Answer is not fully traceable to approved sources"
            ),
            severity=Severity.BLOCKER if not has_citations else Severity.INFO,
        )
    )
    prohibited = find_prohibited(answer)
    checks.append(
        GuardrailCheck(
            id="OUTPUT-PROHIBITED-LANGUAGE",
            passed=not prohibited,
            message=(
                "Answer contains prohibited absolute or curative language"
                if prohibited
                else "No prohibited absolute or curative language"
            ),
            severity=Severity.BLOCKER if prohibited else Severity.INFO,
        )
    )
    grounding = grounding_score(answer, passages)
    checks.append(
        GuardrailCheck(
            id="OUTPUT-GROUNDING",
            passed=grounding >= 0.85,
            message=f"Answer grounding score {grounding:.0%} against cited passages",
            severity=Severity.BLOCKER if grounding < 0.85 else Severity.INFO,
        )
    )
    fair_balance = bool(re.search(r"\b(safety|adverse|side effects)\b", answer, re.IGNORECASE))
    checks.append(
        GuardrailCheck(
            id="OUTPUT-FAIR-BALANCE",
            passed=fair_balance,
            message=(
                "Safety context is present"
                if fair_balance
                else "Answer lacks safety context for promotional content"
            ),
            severity=Severity.BLOCKER if not fair_balance else Severity.INFO,
        )
    )
    within_length = len(answer) <= 3000
    checks.append(
        GuardrailCheck(
            id="OUTPUT-LENGTH",
            passed=within_length,
            message=f"Answer length {len(answer)} characters",
            severity=Severity.BLOCKER if not within_length else Severity.INFO,
        )
    )
    passed = not any(
        check.severity is Severity.BLOCKER and not check.passed for check in checks
    )
    return checks, grounding, passed


def grounding_score(answer: str, passages: list[RetrievedPassage]) -> float:
    """Fraction of substantive answer sentences supported by a cited passage."""

    source_tokens: set[str] = set()
    for passage in passages:
        source_tokens.update(tokenize(f"{passage.heading} {passage.text}"))
    if not source_tokens:
        return 0.0
    supported = 0
    total = 0
    for line in answer.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith(("Based on", "Safety note", "Sources:")):
            continue
        stripped = CITATION_MARKER.sub("", stripped)
        stripped = stripped.lstrip("-* ").strip()
        for sentence in SENTENCE_RE.split(stripped):
            tokens = set(tokenize(sentence))
            if len(tokens) < 4:
                continue
            total += 1
            overlap = len(tokens.intersection(source_tokens)) / len(tokens)
            if overlap >= 0.6:
                supported += 1
    if total == 0:
        return 1.0
    return round(supported / total, 4)
