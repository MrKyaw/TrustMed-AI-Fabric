"""Claims substantiation and evidence validity."""

from __future__ import annotations

from datetime import datetime

from trustmed_fabric.errors import NotFoundError
from trustmed_fabric.language import find_prohibited
from trustmed_fabric.models import (
    Asset,
    Claim,
    ClaimAssessment,
    ClaimStatus,
    Evidence,
    Market,
    PolicyFinding,
    Severity,
)
from trustmed_fabric.store import Store
from trustmed_fabric.timeutil import ensure_utc, utcnow


class ClaimRegistry:
    def __init__(self, store: Store) -> None:
        self.store = store

    def get(self, claim_id: str) -> Claim:
        claim = self.store.get_model("claim", claim_id, Claim)
        if claim is None:
            raise NotFoundError(f"claim {claim_id!r} was not found")
        return claim

    def assess(self, claim_id: str, market: Market, now: datetime | None = None) -> ClaimAssessment:
        as_of = ensure_utc(now or utcnow())
        claim = self.get(claim_id)
        findings: list[PolicyFinding] = []
        evidence: list[Evidence] = []

        if claim.status is not ClaimStatus.APPROVED:
            findings.append(
                PolicyFinding(
                    code="CLAIM-NOT-APPROVED",
                    policy_id="CLM-001",
                    severity=Severity.BLOCKER,
                    message=f"{claim.id} is {claim.status.value.lower()} and cannot be used in promotion",
                    remediation="Route the claim through medical, legal and regulatory review.",
                    field="status",
                )
            )
        if market not in claim.markets:
            findings.append(
                PolicyFinding(
                    code="CLAIM-MARKET-MISMATCH",
                    policy_id="CLM-002",
                    severity=Severity.BLOCKER,
                    message=(
                        f"{claim.id} is approved for {[m.value for m in claim.markets]}, "
                        f"not {market.value}"
                    ),
                    remediation="Use a market-specific approved claim or submit a local adaptation.",
                    field="markets",
                )
            )
        for evidence_id in claim.evidence_ids:
            item = self.store.get_model("evidence", evidence_id, Evidence)
            if item is None:
                findings.append(
                    PolicyFinding(
                        code="CLAIM-EVIDENCE-MISSING",
                        policy_id="CLM-003",
                        severity=Severity.BLOCKER,
                        message=f"{claim.id} references missing evidence {evidence_id}",
                        remediation="Link the claim to an evidence record in the approved library.",
                        field="evidence_ids",
                    )
                )
                continue
            evidence.append(item)
            if not item.valid_on(as_of.date(), market):
                findings.append(
                    PolicyFinding(
                        code="CLAIM-EVIDENCE-INVALID",
                        policy_id="CLM-003",
                        severity=Severity.BLOCKER,
                        message=(
                            f"Evidence {item.id} is not valid for {market.value} on "
                            f"{as_of.date().isoformat()}"
                        ),
                        remediation="Refresh the evidence or withdraw the claim from this market.",
                        field="evidence_ids",
                    )
                )
            if item.strength == "LOW":
                findings.append(
                    PolicyFinding(
                        code="CLAIM-EVIDENCE-WEAK",
                        policy_id="CLM-004",
                        severity=Severity.WARNING,
                        message=f"Evidence {item.id} has low substantiation strength",
                        remediation="Add stronger evidence or qualify the claim precisely.",
                        field="evidence_ids",
                    )
                )
        for text in (claim.text, claim.approved_wording):
            for code, phrase in find_prohibited(text):
                findings.append(
                    PolicyFinding(
                        code=f"CLAIM-PROHIBITED-{code}",
                        policy_id="CLM-005",
                        severity=Severity.BLOCKER,
                        message=f"Claim contains prohibited language: {phrase!r}",
                        remediation="Remove absolute or curative wording and use approved claim text.",
                        field="text",
                    )
                )
        deduped = _dedupe(findings)
        return ClaimAssessment(
            claim_id=claim.id,
            claim_text=claim.text,
            market=market,
            status=claim.status,
            allowed=not any(f.severity is Severity.BLOCKER for f in deduped),
            evidence=evidence,
            findings=deduped,
            evaluated_at=as_of,
        )

    def validate_asset_claims(
        self, asset: Asset, market: Market, now: datetime | None = None
    ) -> list[PolicyFinding]:
        findings: list[PolicyFinding] = []
        for claim_id in asset.claim_ids:
            try:
                assessment = self.assess(claim_id, market, now)
            except NotFoundError:
                findings.append(
                    PolicyFinding(
                        code="CLAIM-NOT-FOUND",
                        policy_id="CLM-001",
                        severity=Severity.BLOCKER,
                        message=f"{asset.id} references unknown claim {claim_id}",
                        remediation="Remove the reference or register the claim.",
                        field="claim_ids",
                    )
                )
                continue
            findings.extend(assessment.findings)
        referenced = {claim_id for section in asset.sections for claim_id in section.claim_ids}
        undeclared = referenced.difference(asset.claim_ids)
        for claim_id in sorted(undeclared):
            findings.append(
                PolicyFinding(
                    code="CLAIM-UNDECLARED",
                    policy_id="CLM-006",
                    severity=Severity.BLOCKER,
                    message=f"Section references {claim_id} but the asset does not declare it",
                    remediation="Declare every referenced claim at asset level for traceability.",
                    field="claim_ids",
                )
            )
        return _dedupe(findings)


def _dedupe(findings: list[PolicyFinding]) -> list[PolicyFinding]:
    seen: set[tuple[str, str]] = set()
    result: list[PolicyFinding] = []
    for finding in findings:
        key = (finding.code, finding.message)
        if key not in seen:
            seen.add(key)
            result.append(finding)
    return result
