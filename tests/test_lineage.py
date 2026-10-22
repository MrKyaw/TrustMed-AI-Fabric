from datetime import UTC, datetime

from trustmed_fabric.lineage import governance_gaps, node_id, trace_asset, traceability_coverage


def test_trace_asset_has_nodes_and_edges(service) -> None:
    graph = trace_asset(service.store, "ONC-HCP-DA-001")
    assert graph.root == "asset:ONC-HCP-DA-001"
    assert graph.nodes
    assert graph.edges
    assert graph.counts["asset"] == 1


def test_trace_asset_missing_raises(service) -> None:
    import pytest

    from trustmed_fabric.errors import NotFoundError

    with pytest.raises(NotFoundError):
        trace_asset(service.store, "NOPE-000")


def test_governance_gaps_and_coverage(service) -> None:
    gaps = governance_gaps(service.store, now=datetime(2026, 6, 15, tzinfo=UTC))
    assert any(gap["code"] == "EXPIRED_APPROVAL_IN_MARKET" for gap in gaps)
    coverage = traceability_coverage(service.store)
    assert "coverage_pct" in coverage
    assert coverage["live_publications"] > 0


def test_node_id_format() -> None:
    assert node_id("asset", "ONC-HCP-DA-001") == "asset:ONC-HCP-DA-001"
