from datetime import UTC, datetime

from trustmed_fabric.claims import ClaimRegistry
from trustmed_fabric.models import Market


def test_claim_assess_allowed(seeded_store) -> None:
    registry = ClaimRegistry(seeded_store)
    assessment = registry.assess("CLM-001", Market.US, now=datetime(2026, 6, 15, tzinfo=UTC))
    assert assessment.allowed is True
    assert assessment.evidence
    assert assessment.findings == []


def test_claim_assess_market_mismatch(seeded_store) -> None:
    registry = ClaimRegistry(seeded_store)
    assessment = registry.assess("CLM-001", Market.DE, now=datetime(2026, 6, 15, tzinfo=UTC))
    assert assessment.allowed is False
    assert any(finding.code == "CLAIM-MARKET-MISMATCH" for finding in assessment.findings)


def test_claim_not_found_raises(seeded_store) -> None:
    import pytest

    from trustmed_fabric.errors import NotFoundError

    registry = ClaimRegistry(seeded_store)
    with pytest.raises(NotFoundError):
        registry.assess("CLM-999", Market.US)


def test_claim_validate_asset_claims_undeclared(seeded_store) -> None:
    from trustmed_fabric.models import Asset

    asset = seeded_store.get_model("asset", "ONC-HCP-DA-001", Asset)
    assert asset is not None
    asset.claim_ids = []
    findings = ClaimRegistry(seeded_store).validate_asset_claims(asset, Market.US)
    assert any(finding.code == "CLAIM-UNDECLARED" for finding in findings)
