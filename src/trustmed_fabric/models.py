"""Immutable, machine-checkable domain models for the TrustMed fabric.

The models are intentionally explicit. In a regulated content ecosystem the
schema *is* part of the control surface: every field that can influence an
approval, a publication or an answer is named, typed and validated.
"""

from __future__ import annotations

import hashlib
from datetime import date, datetime
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from trustmed_fabric.canonical import canonical_json


class Market(StrEnum):
    US = "US"
    CA = "CA"
    UK = "UK"
    DE = "DE"
    FR = "FR"


class Audience(StrEnum):
    HCP = "HCP"
    PATIENT = "PATIENT"
    CAREGIVER = "CAREGIVER"


class Channel(StrEnum):
    WEB = "WEB"
    EMAIL = "EMAIL"
    PAID_MEDIA = "PAID_MEDIA"
    DETAIL_AID = "DETAIL_AID"
    FIELD = "FIELD"
    SOCIAL = "SOCIAL"


class AssetType(StrEnum):
    DETAIL_AID = "DETAIL_AID"
    LANDING_PAGE = "LANDING_PAGE"
    EMAIL = "EMAIL"
    BANNER = "BANNER"
    VIDEO = "VIDEO"
    SOCIAL_POST = "SOCIAL_POST"


class AssetStatus(StrEnum):
    DRAFT = "DRAFT"
    IN_REVIEW = "IN_REVIEW"
    APPROVED = "APPROVED"
    RETIRED = "RETIRED"


class ApprovalStatus(StrEnum):
    PENDING = "PENDING"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    WITHDRAWN = "WITHDRAWN"


class ClaimType(StrEnum):
    EFFICACY = "EFFICACY"
    SAFETY = "SAFETY"
    SUPPORT = "SUPPORT"
    BURDEN = "BURDEN"
    HEALTH_ECONOMICS = "HEALTH_ECONOMICS"


class ClaimStatus(StrEnum):
    APPROVED = "APPROVED"
    DRAFT = "DRAFT"
    EXPIRED = "EXPIRED"
    WITHDRAWN = "WITHDRAWN"


class EvidenceType(StrEnum):
    CLINICAL_TRIAL = "CLINICAL_TRIAL"
    LABEL = "LABEL"
    SAFETY_ANALYSIS = "SAFETY_ANALYSIS"
    PATIENT_REPORTED_OUTCOMES = "PATIENT_REPORTED_OUTCOMES"
    REAL_WORLD_EVIDENCE = "REAL_WORLD_EVIDENCE"
    HEALTH_ECONOMICS = "HEALTH_ECONOMICS"
    PROGRAM_DESCRIPTION = "PROGRAM_DESCRIPTION"


class PublicationStatus(StrEnum):
    LIVE = "LIVE"
    PAUSED = "PAUSED"
    RETIRED = "RETIRED"


class ExperienceStatus(StrEnum):
    LIVE = "LIVE"
    PAUSED = "PAUSED"
    RETIRED = "RETIRED"


class PolicyOutcome(StrEnum):
    ALLOW = "ALLOW"
    REVIEW = "REVIEW"
    DENY = "DENY"


class Severity(StrEnum):
    INFO = "INFO"
    WARNING = "WARNING"
    BLOCKER = "BLOCKER"


class ContentSection(BaseModel):
    """A citable unit. Citations always point at a section, never a whole asset."""

    model_config = ConfigDict(extra="forbid")

    id: str = Field(pattern=r"^[a-z0-9][a-z0-9-]{1,63}$")
    heading: str = Field(min_length=2, max_length=200)
    body: str = Field(min_length=10, max_length=8000)
    claim_ids: list[str] = Field(default_factory=list)
    safety_information: bool = False


class Approval(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: ApprovalStatus
    material_id: str = Field(min_length=3, max_length=64)
    approved_by: str = Field(min_length=2, max_length=120)
    review_board: str = Field(min_length=2, max_length=120)
    approved_at: datetime
    expires_at: datetime
    version: int = Field(ge=1)

    @model_validator(mode="after")
    def expires_after_approval(self) -> Approval:
        if self.expires_at <= self.approved_at:
            raise ValueError("expires_at must be later than approved_at")
        return self


class Asset(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str = Field(pattern=r"^[A-Z]{3}-[A-Z]{3}-[A-Z]{2,3}-\d{3}$")
    title: str = Field(min_length=3, max_length=200)
    brand: str = Field(min_length=2, max_length=80)
    therapeutic_area: str = Field(min_length=2, max_length=80)
    asset_type: AssetType
    channel: Channel
    market: Market
    language: str = Field(default="en", pattern=r"^[a-z]{2}(-[A-Z]{2})?$")
    audience: Audience
    status: AssetStatus
    version: int = Field(ge=1)
    summary: str = Field(min_length=10, max_length=1000)
    sections: list[ContentSection] = Field(min_length=1)
    tags: list[str] = Field(min_length=1)
    claim_ids: list[str] = Field(default_factory=list)
    approval: Approval | None = None
    owner: str = Field(min_length=2, max_length=120)
    source_system: str = Field(min_length=2, max_length=80)
    created_at: datetime
    updated_at: datetime
    metadata: dict[str, Any] = Field(default_factory=dict)

    @field_validator("sections")
    @classmethod
    def unique_section_ids(cls, sections: list[ContentSection]) -> list[ContentSection]:
        ids = [section.id for section in sections]
        if len(ids) != len(set(ids)):
            raise ValueError("section ids must be unique within an asset")
        return sections

    @model_validator(mode="after")
    def approved_assets_need_approval(self) -> Asset:
        if self.status is AssetStatus.APPROVED and self.approval is None:
            raise ValueError("APPROVED assets require an approval record")
        if self.approval is not None and self.approval.status is ApprovalStatus.APPROVED:
            referenced = {claim for section in self.sections for claim in section.claim_ids}
            if not referenced.issubset(set(self.claim_ids)):
                raise ValueError("section claim_ids must be a subset of asset claim_ids")
        return self

    @property
    def content_hash(self) -> str:
        payload = {
            "id": self.id,
            "version": self.version,
            "title": self.title,
            "summary": self.summary,
            "sections": [s.model_dump(mode="json") for s in self.sections],
            "claim_ids": sorted(self.claim_ids),
        }
        return hashlib.sha256(canonical_json(payload).encode()).hexdigest()

    @property
    def has_safety_section(self) -> bool:
        return any(s.safety_information for s in self.sections)


class Evidence(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str = Field(pattern=r"^EV-\d{3}$")
    title: str = Field(min_length=3, max_length=240)
    evidence_type: EvidenceType
    citation: str = Field(min_length=5, max_length=400)
    markets: list[Market] = Field(min_length=1)
    effective_at: date
    expires_at: date
    strength: str = Field(pattern=r"^(HIGH|MODERATE|LOW)$")
    source_system: str = Field(default="evidence-library", min_length=2)
    synthetic: bool = True

    @model_validator(mode="after")
    def valid_window(self) -> Evidence:
        if self.expires_at <= self.effective_at:
            raise ValueError("evidence expiry must be later than effective date")
        return self

    def valid_on(self, day: date, market: Market) -> bool:
        return market in self.markets and self.effective_at <= day <= self.expires_at


class Claim(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str = Field(pattern=r"^CLM-\d{3}$")
    text: str = Field(min_length=10, max_length=1000)
    claim_type: ClaimType
    evidence_ids: list[str] = Field(min_length=1)
    markets: list[Market] = Field(min_length=1)
    status: ClaimStatus
    approved_wording: str = Field(min_length=10, max_length=1000)
    reviewed_at: date
    tags: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def wording_matches_claim(self) -> Claim:
        if not self.approved_wording.strip():
            raise ValueError("approved_wording cannot be blank")
        return self


class Experience(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str = Field(pattern=r"^EXP-[A-Z0-9-]{3,40}$")
    name: str = Field(min_length=3, max_length=160)
    channel: Channel
    market: Market
    audience: Audience
    url: str = Field(min_length=3, max_length=300)
    design_system_version: str = Field(min_length=2, max_length=40)
    surface_version: str = Field(min_length=2, max_length=40)
    status: ExperienceStatus
    consent_required: bool = False
    tracking_plan_id: str = Field(min_length=3, max_length=80)
    launched_at: datetime
    owner: str = Field(min_length=2, max_length=120)


class Publication(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str = Field(pattern=r"^PUB-\d{3}$")
    asset_id: str
    asset_version: int = Field(ge=1)
    experience_id: str
    channel: Channel
    market: Market
    destination: str = Field(min_length=3, max_length=300)
    external_id: str = Field(min_length=3, max_length=120)
    published_at: datetime
    content_hash: str = Field(pattern=r"^[a-f0-9]{64}$")
    status: PublicationStatus
    actor: str = Field(default="publisher-service", min_length=2)


class Metric(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str = Field(pattern=r"^MET-[A-Z0-9-]{3,50}$")
    experience_id: str
    publication_id: str
    metric_date: date
    impressions: int = Field(ge=0)
    engagements: int = Field(ge=0)
    conversions: int = Field(ge=0)
    source_system: str = Field(min_length=2, max_length=80)
    attribution_model: str = Field(min_length=3, max_length=80)
    consent_basis: str = Field(min_length=3, max_length=80)
    quality_score: float = Field(ge=0, le=1)

    @model_validator(mode="after")
    def engagements_within_impressions(self) -> Metric:
        if self.engagements > self.impressions:
            raise ValueError("engagements cannot exceed impressions")
        if self.conversions > self.engagements:
            raise ValueError("conversions cannot exceed engagements")
        return self


class Insight(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str = Field(pattern=r"^INS-\d{3}$")
    experience_id: str
    publication_id: str
    title: str = Field(min_length=3, max_length=200)
    finding: str = Field(min_length=10, max_length=2000)
    recommendation: str = Field(min_length=10, max_length=2000)
    metric_ids: list[str] = Field(min_length=1)
    confidence: float = Field(ge=0, le=1)
    generated_at: datetime


class TaxonomyTerm(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str = Field(pattern=r"^[a-z_]+:[a-z0-9-]+$")
    dimension: str = Field(min_length=2, max_length=40)
    label: str = Field(min_length=2, max_length=80)
    synonyms: list[str] = Field(default_factory=list)
    status: str = Field(pattern=r"^(ACTIVE|DEPRECATED)$")
    version: int = Field(ge=1)


class PolicyFinding(BaseModel):
    code: str
    policy_id: str
    severity: Severity
    message: str
    remediation: str = ""
    field: str | None = None


class PolicyDecision(BaseModel):
    outcome: PolicyOutcome
    score: int = Field(ge=0, le=100)
    findings: list[PolicyFinding]
    policy_version: str
    evaluated_at: datetime
    asset_id: str
    asset_version: int
    context: dict[str, Any] = Field(default_factory=dict)

    @property
    def blockers(self) -> list[PolicyFinding]:
        return [f for f in self.findings if f.severity is Severity.BLOCKER]


class Citation(BaseModel):
    citation_id: str
    asset_id: str
    asset_version: int
    section_id: str
    title: str
    excerpt: str
    deep_link: str
    content_hash: str
    approved_at: datetime
    expires_at: datetime
    market: Market
    audience: Audience
    channel: Channel
    claim_ids: list[str] = Field(default_factory=list)


class GuardrailCheck(BaseModel):
    id: str
    passed: bool
    message: str
    severity: Severity = Severity.INFO


class RetrievedPassage(BaseModel):
    asset_id: str
    asset_version: int
    section_id: str
    heading: str
    text: str
    score: float
    title: str
    market: Market
    audience: Audience
    channel: Channel
    claim_ids: list[str]
    content_hash: str
    approved_at: datetime
    expires_at: datetime


class AskRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    question: str = Field(min_length=5, max_length=500)
    market: Market
    audience: Audience
    channel: Channel | None = None
    limit: int = Field(default=4, ge=1, le=8)
    as_of: datetime | None = None


class AskResponse(BaseModel):
    trace_id: str
    question: str
    answer: str
    refused: bool
    refusal_reason: str | None = None
    citations: list[Citation]
    decision: PolicyDecision | None
    checks: list[GuardrailCheck]
    context_pack: str
    latency_ms: float
    generated_at: datetime
    model: str
    retrieval_meta: dict[str, Any] = Field(default_factory=dict)


class ClaimAssessment(BaseModel):
    claim_id: str
    claim_text: str
    market: Market
    status: ClaimStatus
    allowed: bool
    evidence: list[Evidence]
    findings: list[PolicyFinding]
    evaluated_at: datetime


class LedgerEvent(BaseModel):
    sequence: int
    id: str
    event_type: str
    subject_type: str
    subject_id: str
    occurred_at: datetime
    actor: str
    trace_id: str
    payload: dict[str, Any]
    prev_hash: str
    hash: str


class LineageNode(BaseModel):
    id: str
    type: str
    label: str
    status: str | None = None
    occurred_at: datetime | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class LineageEdge(BaseModel):
    source: str
    target: str
    relation: str
    event_id: str
    occurred_at: datetime


class LineageGraph(BaseModel):
    root: str
    nodes: list[LineageNode]
    edges: list[LineageEdge]
    counts: dict[str, int]
    gaps: list[str] = Field(default_factory=list)
