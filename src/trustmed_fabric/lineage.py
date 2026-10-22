"""Lineage graph traversal, impact analysis and governance gap detection.

Every node is namespaced (``asset:``, ``claim:`` ...) so an edge can be reasoned
about without joining entity tables. Edges are written only as part of a
ledger append, which makes the graph reconstructable from the audit trail.
"""

from __future__ import annotations

from collections import Counter, deque
from datetime import datetime
from typing import Any

from trustmed_fabric.errors import NotFoundError
from trustmed_fabric.models import (
    Asset,
    AssetStatus,
    Claim,
    ClaimStatus,
    Evidence,
    Experience,
    ExperienceStatus,
    Insight,
    LineageEdge,
    LineageGraph,
    LineageNode,
    Metric,
    Publication,
    PublicationStatus,
)
from trustmed_fabric.store import Store
from trustmed_fabric.timeutil import ensure_utc, utcnow


def node_id(entity_type: str, entity_id: str) -> str:
    return f"{entity_type}:{entity_id}"


def _short(text: str, limit: int = 88) -> str:
    return text if len(text) <= limit else text[: limit - 1] + "…"


def _node_for(store: Store, composite: str) -> LineageNode | None:
    entity_type, _, entity_id = composite.partition(":")
    doc = store.get(entity_type, entity_id)
    if doc is None:
        return None
    if entity_type == "asset":
        asset = Asset.model_validate(doc)
        return LineageNode(
            id=composite,
            type="asset",
            label=asset.title,
            status=asset.status.value,
            occurred_at=asset.updated_at,
            metadata={
                "market": asset.market.value,
                "audience": asset.audience.value,
                "version": asset.version,
                "content_hash": asset.content_hash,
                "expires_at": asset.approval.expires_at.isoformat() if asset.approval else None,
            },
        )
    if entity_type == "claim":
        claim = Claim.model_validate(doc)
        return LineageNode(
            id=composite,
            type="claim",
            label=_short(claim.text),
            status=claim.status.value,
            metadata={"claim_type": claim.claim_type.value, "markets": [m.value for m in claim.markets]},
        )
    if entity_type == "evidence":
        evidence = Evidence.model_validate(doc)
        return LineageNode(
            id=composite,
            type="evidence",
            label=evidence.title,
            status=evidence.strength,
            metadata={"citation": evidence.citation, "type": evidence.evidence_type.value},
        )
    if entity_type == "publication":
        publication = Publication.model_validate(doc)
        return LineageNode(
            id=composite,
            type="publication",
            label=publication.external_id,
            status=publication.status.value,
            occurred_at=publication.published_at,
            metadata={
                "destination": publication.destination,
                "asset_version": publication.asset_version,
                "market": publication.market.value,
            },
        )
    if entity_type == "experience":
        experience = Experience.model_validate(doc)
        return LineageNode(
            id=composite,
            type="experience",
            label=experience.name,
            status=experience.status.value,
            occurred_at=experience.launched_at,
            metadata={
                "channel": experience.channel.value,
                "market": experience.market.value,
                "surface_version": experience.surface_version,
                "consent_required": experience.consent_required,
            },
        )
    if entity_type == "metric":
        metric = Metric.model_validate(doc)
        return LineageNode(
            id=composite,
            type="metric",
            label=f"{metric.impressions:,} impressions",
            status="CAPTURED",
            metadata={
                "engagements": metric.engagements,
                "conversions": metric.conversions,
                "metric_date": metric.metric_date.isoformat(),
                "quality_score": metric.quality_score,
                "publication_id": metric.publication_id,
            },
        )
    if entity_type == "insight":
        insight = Insight.model_validate(doc)
        return LineageNode(
            id=composite,
            type="insight",
            label=insight.title,
            status="GENERATED",
            occurred_at=insight.generated_at,
            metadata={"confidence": insight.confidence, "finding": insight.finding},
        )
    return LineageNode(
        id=composite,
        type=entity_type,
        label=entity_id,
        metadata={},
    )


def _adjacency(edges: list[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    adjacency: dict[str, list[dict[str, Any]]] = {}
    for edge in edges:
        adjacency.setdefault(edge["source"], []).append(edge)
    return adjacency


def _subgraph(store: Store, root: str) -> LineageGraph:
    if _node_for(store, root) is None:
        raise NotFoundError(f"lineage root {root!r} does not exist")
    all_edges = store.edges()
    adjacency = _adjacency(all_edges)
    queue: deque[str] = deque([root])
    seen = {root}
    selected_edges: list[dict[str, Any]] = []
    while queue:
        current = queue.popleft()
        for edge in adjacency.get(current, []):
            selected_edges.append(edge)
            if edge["target"] not in seen:
                seen.add(edge["target"])
                queue.append(edge["target"])
    nodes = []
    for composite in sorted(seen):
        node = _node_for(store, composite)
        if node is not None:
            nodes.append(node)
    edges = [
        LineageEdge(
            source=edge["source"],
            target=edge["target"],
            relation=edge["relation"],
            event_id=edge["event_id"],
            occurred_at=datetime.fromisoformat(edge["occurred_at"]),
        )
        for edge in sorted(selected_edges, key=lambda e: (e["occurred_at"], e["id"]))
    ]
    counts = Counter(node.type for node in nodes)
    return LineageGraph(
        root=root,
        nodes=nodes,
        edges=edges,
        counts=dict(sorted(counts.items())),
        gaps=_graph_gaps(store, nodes, root),
    )


def _graph_gaps(store: Store, nodes: list[LineageNode], root: str) -> list[str]:
    gaps: list[str] = []
    node_types = {node.type for node in nodes}
    if root.startswith("asset:"):
        if "publication" not in node_types:
            gaps.append("No publication is linked to this asset")
        elif "metric" not in node_types:
            gaps.append("Published content has no captured measurement")
        elif "insight" not in node_types:
            gaps.append("Measurement exists but has not produced a documented insight")
    publications = [node for node in nodes if node.type == "publication"]
    for publication in publications:
        metadata = publication.metadata
        if metadata.get("asset_version") is None:
            gaps.append(f"{publication.label} has no asset version pinned")
    return gaps


def trace_asset(store: Store, asset_id: str) -> LineageGraph:
    return _subgraph(store, node_id("asset", asset_id))


def trace_entity(store: Store, entity_type: str, entity_id: str) -> LineageGraph:
    return _subgraph(store, node_id(entity_type, entity_id))


def governance_gaps(store: Store, now: datetime | None = None) -> list[dict[str, Any]]:
    """Cross-cutting gaps that no single platform team can see alone."""

    as_of = ensure_utc(now or utcnow())
    gaps: list[dict[str, Any]] = []
    assets = store.list_models("asset", Asset)
    publications = store.list_models("publication", Publication)
    experiences = {
        experience.id: experience for experience in store.list_models("experience", Experience)
    }
    metric_publications = {
        metric.publication_id for metric in store.list_models("metric", Metric)
    }
    insight_publications = {
        insight.publication_id for insight in store.list_models("insight", Insight)
    }
    published_asset_ids = {publication.asset_id for publication in publications}

    for asset in assets:
        if asset.status is AssetStatus.APPROVED and asset.approval:
            if asset.approval.expires_at <= as_of:
                planned = [
                    p.id
                    for p in publications
                    if p.asset_id == asset.id and p.status is PublicationStatus.LIVE
                ]
                gaps.append(
                    {
                        "code": "EXPIRED_APPROVAL_IN_MARKET",
                        "severity": "HIGH",
                        "subject": asset.id,
                        "message": (
                            f"{asset.id} approval expired on "
                            f"{asset.approval.expires_at.date().isoformat()}"
                            + (f" but remains linked to live publications {planned}" if planned else "")
                        ),
                    }
                )
            elif asset.id not in published_asset_ids:
                gaps.append(
                    {
                        "code": "APPROVED_NOT_PUBLISHED",
                        "severity": "LOW",
                        "subject": asset.id,
                        "message": f"{asset.id} is approved but has no publication record",
                    }
                )

    for publication in publications:
        experience = experiences.get(publication.experience_id)
        if experience is None:
            gaps.append(
                {
                    "code": "PUBLICATION_WITHOUT_EXPERIENCE",
                    "severity": "HIGH",
                    "subject": publication.id,
                    "message": f"{publication.id} points at a missing experience",
                }
            )
        elif experience.status is ExperienceStatus.LIVE and publication.status is PublicationStatus.LIVE:
            if publication.id not in metric_publications:
                gaps.append(
                    {
                        "code": "LIVE_WITHOUT_MEASUREMENT",
                        "severity": "MEDIUM",
                        "subject": publication.id,
                        "message": f"{publication.id} is live but has no measurement rows",
                    }
                )
            elif publication.id not in insight_publications:
                gaps.append(
                    {
                        "code": "MEASURED_WITHOUT_INSIGHT",
                        "severity": "LOW",
                        "subject": publication.id,
                        "message": f"{publication.id} has measurement but no linked insight",
                    }
                )

    claims = {claim.id: claim for claim in store.list_models("claim", Claim)}
    for claim in claims.values():
        if claim.status is ClaimStatus.APPROVED:
            evidence = [
                store.get_model("evidence", evidence_id, Evidence)
                for evidence_id in claim.evidence_ids
            ]
            valid = [
                e
                for e in evidence
                if e is not None and any(e.valid_on(as_of.date(), market) for market in claim.markets)
            ]
            if not valid:
                gaps.append(
                    {
                        "code": "CLAIM_WITHOUT_VALID_EVIDENCE",
                        "severity": "HIGH",
                        "subject": claim.id,
                        "message": f"{claim.id} is approved but has no evidence valid today",
                    }
                )
    return gaps


def traceability_coverage(store: Store) -> dict[str, Any]:
    """Percentage of live publications with a complete, inspectable chain."""

    publications = [
        p
        for p in store.list_models("publication", Publication)
        if p.status is PublicationStatus.LIVE
    ]
    metric_ids = {
        metric.publication_id for metric in store.list_models("metric", Metric)
    }
    experiences = {e.id for e in store.list_models("experience", Experience)}
    complete = [
        p
        for p in publications
        if p.experience_id in experiences
        and p.id in metric_ids
        and str(node_id("asset", p.asset_id))
    ]
    coverage = (len(complete) / len(publications) * 100) if publications else 100.0
    return {
        "live_publications": len(publications),
        "fully_traceable": len(complete),
        "coverage_pct": round(coverage, 1),
        "publications_without_measurement": sorted(
            p.id for p in publications if p.id not in metric_ids
        ),
    }
