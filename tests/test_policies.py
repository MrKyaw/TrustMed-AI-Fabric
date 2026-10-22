from datetime import UTC, datetime

from trustmed_fabric.models import Audience, Channel, Market, PolicyOutcome


def test_policy_allow_for_approved_asset(service) -> None:
    decision = service.evaluate(
        "ONC-HCP-DA-001",
        Market.US,
        Audience.HCP,
        Channel.WEB,
        experience_id="EXP-WEB-US-ONC-HCP",
        now=datetime(2026, 6, 15, tzinfo=UTC),
    )
    assert decision.outcome is PolicyOutcome.ALLOW
    assert decision.score == 100
    assert decision.findings == []


def test_policy_denies_wrong_market(service) -> None:
    decision = service.evaluate(
        "ONC-HCP-DA-001",
        Market.UK,
        Audience.HCP,
        Channel.WEB,
        now=datetime(2026, 6, 15, tzinfo=UTC),
    )
    assert decision.outcome is PolicyOutcome.DENY
    assert any(finding.code == "MARKET-MISMATCH" for finding in decision.findings)


def test_policy_catalog_and_evaluation_endpoint(client) -> None:
    response = client.get("/api/v1/policy/catalog")
    assert response.status_code == 200
    assert response.json()["count"] >= 12
    evaluate = client.post(
        "/api/v1/policy/evaluate",
        json={"asset_id": "ONC-HCP-DA-001", "market": "US", "audience": "HCP", "channel": "WEB"},
    )
    assert evaluate.status_code == 200
    assert evaluate.json()["outcome"] == "ALLOW"
