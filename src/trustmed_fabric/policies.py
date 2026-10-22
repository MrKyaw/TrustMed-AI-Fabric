"""Composable policy engine for content, claims, privacy and platform fit."""

from __future__ import annotations

from datetime import timedelta
from typing import Any

from trustmed_fabric.claims import ClaimRegistry
from trustmed_fabric.errors import NotFoundError
from trustmed_fabric.language import find_pii, find_prohibited
from trustmed_fabric.models import (
    Asset,
    AssetStatus,
    Audience,
    Channel,
    Claim,
    ClaimType,
    Experience,
    ExperienceStatus,
    Market,
    PolicyDecision,
    PolicyFinding,
    PolicyOutcome,
    Severity,
)
from trustmed_fabric.store import Store
from trustmed_fabric.surfaces import is_supported, surface_status
from trustmed_fabric.taxonomy import Taxonomy
from trustmed_fabric.timeutil import ensure_utc, utcnow

POLICY_VERSION = "2026.1"
REVIEW_WINDOW_DAYS = 30

POLICY_CATALOG: list[dict[str, str]] = [
    {
        "id": "MLR-001",
        "name": "Approved material required",
        "description": "Promotional content must carry a current medical, legal and regulatory approval.",
        "category": "Review and approval",
        "severity": "BLOCKER",
    },
    {
        "id": "MLR-002",
        "name": "Approval expiry",
        "description": "Expired approvals cannot be retrieved, published or used by the assistant.",
        "category": "Review and approval",
        "severity": "BLOCKER",
    },
    {
        "id": "MLR-003",
        "name": "Version pinning",
        "description": "The approved version must match the asset version being distributed.",
        "category": "Review and approval",
        "severity": "BLOCKER",
    },
    {
        "id": "MKT-001",
        "name": "Market and audience fit",
        "description": "Content can only be used in its approved market, audience and channel.",
        "category": "Market fit",
        "severity": "BLOCKER",
    },
    {
        "id": "MKT-004",
        "name": "Experience fit",
        "description": "A publication must match the market, audience and channel of its experience.",
        "category": "Market fit",
        "severity": "BLOCKER",
    },
    {
        "id": "TAX-001",
        "name": "Controlled taxonomy",
        "description": "Every tag must resolve to an active, versioned taxonomy term.",
        "category": "Metadata",
        "severity": "BLOCKER",
    },
    {
        "id": "CLM-001",
        "name": "Claim substantiation",
        "description": "Every claim must be approved, market-valid and backed by valid evidence.",
        "category": "Claims",
        "severity": "BLOCKER",
    },
    {
        "id": "CLM-005",
        "name": "Prohibited language",
        "description": "Curative, guaranteed or absolute claims are blocked before review.",
        "category": "Claims",
        "severity": "BLOCKER",
    },
    {
        "id": "CLM-101",
        "name": "Fair balance",
        "description": "Efficacy claims require a clearly identifiable safety information section.",
        "category": "Claims",
        "severity": "BLOCKER",
    },
    {
        "id": "PRV-001",
        "name": "Consent and tracking basis",
        "description": "Patient-directed experiences must declare consent and a tracking plan.",
        "category": "Privacy",
        "severity": "BLOCKER",
    },
    {
        "id": "PRV-002",
        "name": "Personal data in content",
        "description": "Promotional content must not contain email addresses, phone numbers or record numbers.",
        "category": "Privacy",
        "severity": "BLOCKER",
    },
    {
        "id": "PLT-001",
        "name": "Supported partner surface",
        "description": "New publications must target a supported partner release; deprecated surfaces require migration.",
        "category": "Platform",
        "severity": "BLOCKER",
    },
]


class PolicyEngine:
    def __init__(self, store: Store, taxonomy: Taxonomy, claims: ClaimRegistry) -> None:
        self.store = store
        self.taxonomy = taxonomy
        self.claims = claims

    def evaluate(
        self,
        asset_id: str,
        market: Market,
        audience: Audience,
        channel: Channel,
        *,
        experience_id: str | None = None,
        now: Any = None,
        for_publication: bool = False,
    ) -> PolicyDecision:
        as_of = ensure_utc(now or utcnow())
        asset = self.store.get_model("asset", asset_id, Asset)
        if asset is None:
            raise NotFoundError(f"asset {asset_id!r} was not found")
        experience = (
            self.store.get_model("experience", experience_id, Experience)
            if experience_id
            else None
        )
        findings: list[PolicyFinding] = []

        findings.extend(self._approval_findings(asset, as_of))
        findings.extend(self._fit_findings(asset, market, audience, channel, experience))
        findings.extend(self.taxonomy.validate_asset(asset))
        findings.extend(self.claims.validate_asset_claims(asset, market, as_of))
        findings.extend(self._content_findings(asset))
        findings.extend(self._privacy_findings(asset, audience, channel, experience))
        findings.extend(self._platform_findings(experience, for_publication))

        deduped = _dedupe(findings)
        blockers = sum(1 for finding in deduped if finding.severity is Severity.BLOCKER)
        warnings = sum(1 for finding in deduped if finding.severity is Severity.WARNING)
        if blockers:
            outcome = PolicyOutcome.DENY
        elif warnings:
            outcome = PolicyOutcome.REVIEW
        else:
            outcome = PolicyOutcome.ALLOW
        score = max(0, 100 - blockers * 22 - warnings * 5)
        return PolicyDecision(
            outcome=outcome,
            score=score,
            findings=deduped,
            policy_version=POLICY_VERSION,
            evaluated_at=as_of,
            asset_id=asset.id,
            asset_version=asset.version,
            context={
                "market": market.value,
                "audience": audience.value,
                "channel": channel.value,
                "experience_id": experience_id,
                "for_publication": for_publication,
                "taxonomy_version": self.taxonomy.version,
            },
        )

    def evaluate_publication(self, publication_id: str, now: Any = None) -> PolicyDecision:
        from trustmed_fabric.models import Publication

        publication = self.store.get_model("publication", publication_id, Publication)
        if publication is None:
            raise NotFoundError(f"publication {publication_id!r} was not found")
        return self.evaluate(
            publication.asset_id,
            publication.market,
            self._audience_for_experience(publication.experience_id),
            publication.channel,
            experience_id=publication.experience_id,
            now=now,
        )

    def _audience_for_experience(self, experience_id: str) -> Audience:
        experience = self.store.get_model("experience", experience_id, Experience)
        return experience.audience if experience else Audience.PATIENT

    def _approval_findings(self, asset: Asset, as_of: Any) -> list[PolicyFinding]:
        findings: list[PolicyFinding] = []
        approval = asset.approval
        if asset.status is not AssetStatus.APPROVED:
            findings.append(
                PolicyFinding(
                    code="ASSET-NOT-APPROVED",
                    policy_id="MLR-001",
                    severity=Severity.BLOCKER,
                    message=f"{asset.id} is {asset.status.value.lower()}, not approved",
                    remediation="Complete review and approval before distribution.",
                    field="status",
                )
            )
        if approval is None or approval.status.value != "APPROVED":
            findings.append(
                PolicyFinding(
                    code="APPROVAL-MISSING",
                    policy_id="MLR-001",
                    severity=Severity.BLOCKER,
                    message="No current approval record is attached to this asset",
                    remediation="Attach an approved material record with a review board and expiry.",
                    field="approval",
                )
            )
            return findings
        if approval.version != asset.version:
            findings.append(
                PolicyFinding(
                    code="APPROVAL-VERSION-MISMATCH",
                    policy_id="MLR-003",
                    severity=Severity.BLOCKER,
                    message=(
                        f"Approval is for version {approval.version}, but asset is version "
                        f"{asset.version}"
                    ),
                    remediation="Publish the approved version or re-approve the current version.",
                    field="version",
                )
            )
        if approval.expires_at <= as_of:
            findings.append(
                PolicyFinding(
                    code="APPROVAL-EXPIRED",
                    policy_id="MLR-002",
                    severity=Severity.BLOCKER,
                    message=(
                        f"Approval expired on {approval.expires_at.date().isoformat()}; "
                        "the asset cannot be used for promotion"
                    ),
                    remediation="Re-submit for review or retire the content.",
                    field="approval.expires_at",
                )
            )
        elif approval.expires_at <= as_of + timedelta(days=REVIEW_WINDOW_DAYS):
            findings.append(
                PolicyFinding(
                    code="APPROVAL-EXPIRING",
                    policy_id="MLR-002",
                    severity=Severity.WARNING,
                    message=(
                        f"Approval expires within {REVIEW_WINDOW_DAYS} days on "
                        f"{approval.expires_at.date().isoformat()}"
                    ),
                    remediation="Start the re-approval workflow and prepare a replacement.",
                    field="approval.expires_at",
                )
            )
        return findings

    def _fit_findings(
        self,
        asset: Asset,
        market: Market,
        audience: Audience,
        channel: Channel,
        experience: Experience | None,
    ) -> list[PolicyFinding]:
        findings: list[PolicyFinding] = []
        if asset.market is not market:
            findings.append(
                PolicyFinding(
                    code="MARKET-MISMATCH",
                    policy_id="MKT-001",
                    severity=Severity.BLOCKER,
                    message=f"{asset.id} is approved for {asset.market.value}, not {market.value}",
                    remediation="Use market-specific approved content.",
                    field="market",
                )
            )
        if asset.audience is not audience:
            findings.append(
                PolicyFinding(
                    code="AUDIENCE-MISMATCH",
                    policy_id="MKT-001",
                    severity=Severity.BLOCKER,
                    message=(
                        f"{asset.id} is written for {asset.audience.value}, not {audience.value}"
                    ),
                    remediation="Use content approved for the intended audience.",
                    field="audience",
                )
            )
        if asset.channel is not channel:
            findings.append(
                PolicyFinding(
                    code="CHANNEL-MISMATCH",
                    policy_id="MKT-001",
                    severity=Severity.BLOCKER,
                    message=f"{asset.id} is approved for {asset.channel.value}, not {channel.value}",
                    remediation="Use a channel-specific approved asset.",
                    field="channel",
                )
            )
        if experience is None:
            return findings
        if (
            experience.market is not market
            or experience.audience is not audience
            or experience.channel is not channel
        ):
            findings.append(
                PolicyFinding(
                    code="EXPERIENCE-MISMATCH",
                    policy_id="MKT-004",
                    severity=Severity.BLOCKER,
                    message=(
                        f"{experience.id} is a {experience.market.value}/"
                        f"{experience.audience.value}/{experience.channel.value} experience"
                    ),
                    remediation="Publish through an experience that matches the approval.",
                    field="experience_id",
                )
            )
        if experience.status is not ExperienceStatus.LIVE:
            findings.append(
                PolicyFinding(
                    code="EXPERIENCE-NOT-LIVE",
                    policy_id="MKT-004",
                    severity=Severity.BLOCKER,
                    message=f"{experience.id} is {experience.status.value.lower()}",
                    remediation="Activate the experience before adding a publication.",
                    field="experience_id",
                )
            )
        return findings

    def _content_findings(self, asset: Asset) -> list[PolicyFinding]:
        findings: list[PolicyFinding] = []
        for section in asset.sections:
            for code, phrase in find_prohibited(f"{section.heading} {section.body}"):
                findings.append(
                    PolicyFinding(
                        code=f"CONTENT-PROHIBITED-{code}",
                        policy_id="CLM-005",
                        severity=Severity.BLOCKER,
                        message=f"Prohibited language in section {section.id}: {phrase!r}",
                        remediation="Rewrite using approved, non-absolute wording.",
                        field=f"sections.{section.id}",
                    )
                )
        efficacy_claims = set()
        for claim_id in asset.claim_ids:
            claim = self.store.get_model("claim", claim_id, Claim)
            if claim is not None and claim.claim_type is ClaimType.EFFICACY:
                efficacy_claims.add(claim_id)
        if efficacy_claims and not asset.has_safety_section:
            findings.append(
                PolicyFinding(
                    code="FAIR-BALANCE-MISSING",
                    policy_id="CLM-101",
                    severity=Severity.BLOCKER,
                    message="Efficacy content requires an explicit safety information section",
                    remediation="Add fair balance with important safety information.",
                    field="sections",
                )
            )
        return findings

    def _privacy_findings(
        self,
        asset: Asset,
        audience: Audience,
        channel: Channel,
        experience: Experience | None,
    ) -> list[PolicyFinding]:
        findings: list[PolicyFinding] = []
        content = " ".join(
            [asset.title, asset.summary, *(section.body for section in asset.sections)]
        )
        for kind in sorted(set(find_pii(content))):
            findings.append(
                PolicyFinding(
                    code=f"PII-IN-CONTENT-{kind.upper()}",
                    policy_id="PRV-002",
                    severity=Severity.BLOCKER,
                    message=f"Content contains a {kind}; promotional assets must not carry personal data",
                    remediation="Remove or tokenise personal data before review.",
                    field="content",
                )
            )
        if audience is Audience.PATIENT and channel in {
            Channel.EMAIL,
            Channel.SOCIAL,
            Channel.PAID_MEDIA,
        }:
            if experience is None or not experience.consent_required:
                findings.append(
                    PolicyFinding(
                        code="CONSENT-NOT-DECLARED",
                        policy_id="PRV-001",
                        severity=Severity.BLOCKER,
                        message="Patient email, social and paid media require an explicit consent basis",
                        remediation="Declare consent in the experience and link a tracking plan.",
                        field="experience.consent_required",
                    )
                )
            elif not experience.tracking_plan_id.strip():
                findings.append(
                    PolicyFinding(
                        code="TRACKING-PLAN-MISSING",
                        policy_id="PRV-001",
                        severity=Severity.BLOCKER,
                        message=f"{experience.id} has no tracking plan",
                        remediation="Attach an approved measurement plan before activation.",
                        field="experience.tracking_plan_id",
                    )
                )
        return findings

    def _platform_findings(
        self, experience: Experience | None, for_publication: bool
    ) -> list[PolicyFinding]:
        if experience is None or is_supported(experience.surface_version):
            return []
        status = surface_status(experience.surface_version)
        return [
            PolicyFinding(
                code="SURFACE-DEPRECATED",
                policy_id="PLT-001",
                severity=Severity.BLOCKER if for_publication else Severity.WARNING,
                message=(
                    f"{experience.id} runs on {experience.surface_version}, which is {status.lower()}"
                ),
                remediation="Migrate to a supported partner surface before the next release window.",
                field="experience.surface_version",
            )
        ]


def _dedupe(findings: list[PolicyFinding]) -> list[PolicyFinding]:
    seen: set[tuple[str, str]] = set()
    result: list[PolicyFinding] = []
    for finding in findings:
        key = (finding.code, finding.message)
        if key not in seen:
            seen.add(key)
            result.append(finding)
    return result
