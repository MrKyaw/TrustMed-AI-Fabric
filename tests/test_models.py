from datetime import UTC, datetime

import pytest

from trustmed_fabric.models import (
    Approval,
    ApprovalStatus,
    Asset,
    AssetStatus,
    ContentSection,
    Evidence,
    Market,
)


def test_content_section_requires_body_minimum() -> None:
    with pytest.raises(ValueError):
        ContentSection(id="intro", heading="Heading", body="short")


def test_approval_expires_after_approval() -> None:
    with pytest.raises(ValueError):
        Approval(
            status=ApprovalStatus.APPROVED,
            material_id="MAT-1",
            approved_by="Reviewer",
            review_board="Board",
            approved_at=datetime(2026, 6, 15, tzinfo=UTC),
            expires_at=datetime(2026, 6, 14, tzinfo=UTC),
            version=1,
        )


def test_approved_asset_requires_approval() -> None:
    with pytest.raises(ValueError):
        Asset(
            id="ONC-HCP-DA-001",
            title="Title",
            brand="ONCRAVIA",
            therapeutic_area="oncology",
            asset_type="DETAIL_AID",
            channel="WEB",
            market="US",
            audience="HCP",
            status=AssetStatus.APPROVED,
            version=1,
            summary="This is a valid summary for an asset.",
            sections=[ContentSection(id="intro", heading="Heading", body="This is a valid body for an approved asset.")],
            tags=["therapeutic_area:oncology"],
            claim_ids=[],
            owner="Owner",
            source_system="content-studio",
            created_at=datetime(2026, 6, 1, tzinfo=UTC),
            updated_at=datetime(2026, 6, 1, tzinfo=UTC),
        )


def test_content_hash_changes_with_version() -> None:
    section = ContentSection(id="intro", heading="Heading", body="This is a valid body for an approved asset.")
    base = dict(
        id="ONC-HCP-DA-001",
        title="Title",
        brand="ONCRAVIA",
        therapeutic_area="oncology",
        asset_type="DETAIL_AID",
        channel="WEB",
        market="US",
        audience="HCP",
        status=AssetStatus.DRAFT,
        version=1,
        summary="This is a valid summary for an asset.",
        sections=[section],
        tags=["therapeutic_area:oncology"],
        claim_ids=[],
        owner="Owner",
        source_system="content-studio",
        created_at=datetime(2026, 6, 1, tzinfo=UTC),
        updated_at=datetime(2026, 6, 1, tzinfo=UTC),
    )
    first = Asset.model_validate(base)
    second = Asset.model_validate({**base, "version": 2})
    assert first.content_hash != second.content_hash


def test_evidence_valid_on_date_and_market() -> None:
    evidence = Evidence(
        id="EV-001",
        title="Evidence",
        evidence_type="CLINICAL_TRIAL",
        citation="A synthetic citation for evidence.",
        markets=[Market.US],
        effective_at=datetime(2026, 1, 1).date(),
        expires_at=datetime(2026, 12, 31).date(),
        strength="HIGH",
    )
    assert evidence.valid_on(datetime(2026, 6, 15).date(), Market.US)
    assert not evidence.valid_on(datetime(2026, 6, 15).date(), Market.UK)
    assert not evidence.valid_on(datetime(2027, 1, 1).date(), Market.US)
