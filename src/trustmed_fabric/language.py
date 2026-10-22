"""Language controls shared by content validation, claims and the assistant.

The controls fail closed. A false positive is a review conversation; a false
negative is an unapproved statement in front of a patient.
"""

from __future__ import annotations

import re

PROHIBITED_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    (
        "CURATIVE_CLAIM",
        re.compile(
            r"\b(cure|cures|cured|curative|miracle|guaranteed?|risk[- ]free|"
            r"no side effects|100% safe|works for everyone|always works)\b",
            re.IGNORECASE,
        ),
    ),
    (
        "ABSOLUTE_CLAIM",
        re.compile(r"\b(never fails|completely safe|zero risk|no risk at all)\b", re.IGNORECASE),
    ),
)

INJECTION_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"\bignore (all )?(previous|prior|above) instructions?\b", re.IGNORECASE),
    re.compile(r"\b(reveal|print|show|leak) (your |the )?(hidden )?(system )?prompt\b", re.IGNORECASE),
    re.compile(r"\b(system prompt|developer message|api key|secret key)\b", re.IGNORECASE),
    re.compile(r"\byou are now (dan|developer mode|jailbroken)\b", re.IGNORECASE),
    re.compile(r"\bjailbreak\b", re.IGNORECASE),
)

CLINICAL_ADVICE_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"\bwhat should i (take|prescribe|recommend to my patient)\b", re.IGNORECASE),
    re.compile(r"\bshould i prescribe\b", re.IGNORECASE),
    re.compile(r"\b(prescribe|dose) for my patient\b", re.IGNORECASE),
    re.compile(r"\bdiagnose me\b", re.IGNORECASE),
)

UNAPPROVED_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(
        r"\b(unapproved|not approved|draft|social post|before approval|withdrawn|expired|archived)\b",
        re.IGNORECASE,
    ),
)

EMAIL_RE = re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b")
PHONE_RE = re.compile(r"(?<!\d)(?:\+?\d[\d\s().-]{8,}\d)(?!\d)")
SSN_RE = re.compile(r"\b\d{3}-\d{2}-\d{4}\b")
MRN_RE = re.compile(r"\b(?:MRN|mrn)[:\s#-]*\d{5,}\b")


def find_prohibited(text: str) -> list[tuple[str, str]]:
    hits: list[tuple[str, str]] = []
    for code, pattern in PROHIBITED_PATTERNS:
        for match in pattern.finditer(text):
            hits.append((code, match.group(0)))
    return hits


def contains_injection(text: str) -> bool:
    return any(pattern.search(text) for pattern in INJECTION_PATTERNS)


def asks_for_clinical_advice(text: str) -> bool:
    return any(pattern.search(text) for pattern in CLINICAL_ADVICE_PATTERNS)


def references_unapproved_content(text: str) -> bool:
    return any(pattern.search(text) for pattern in UNAPPROVED_PATTERNS)


def find_pii(text: str) -> list[str]:
    kinds: list[str] = []
    if EMAIL_RE.search(text):
        kinds.append("email")
    for match in PHONE_RE.finditer(text):
        digits = re.sub(r"\D", "", match.group(0))
        if 10 <= len(digits) <= 15:
            kinds.append("phone")
            break
    if SSN_RE.search(text):
        kinds.append("ssn")
    if MRN_RE.search(text):
        kinds.append("medical-record-number")
    return kinds


def redact_pii(text: str) -> str:
    text = EMAIL_RE.sub("[redacted-email]", text)
    text = SSN_RE.sub("[redacted-ssn]", text)
    text = MRN_RE.sub("[redacted-mrn]", text)

    def _phone(match: re.Match[str]) -> str:
        digits = re.sub(r"\D", "", match.group(0))
        return "[redacted-phone]" if 10 <= len(digits) <= 15 else match.group(0)

    return PHONE_RE.sub(_phone, text)
