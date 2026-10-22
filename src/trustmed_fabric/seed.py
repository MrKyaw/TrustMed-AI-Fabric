"""Deterministic, synthetic seed data for the reference platform.

Dates are relative to a supplied anchor so the demo never looks stale. Passing
a fixed anchor makes the ledger hashes and evaluation results reproducible.
"""

from __future__ import annotations

import random
from collections import Counter
from datetime import UTC, date, datetime, time, timedelta
from typing import Any

from trustmed_fabric.fixtures import content_pack, seed_pack
from trustmed_fabric.lineage import node_id
from trustmed_fabric.models import (
    Approval,
    ApprovalStatus,
    Asset,
    Claim,
    ClaimStatus,
    Evidence,
    Experience,
    Insight,
    Metric,
    Publication,
    PublicationStatus,
    TaxonomyTerm,
)
from trustmed_fabric.store import Store
from trustmed_fabric.taxonomy import Taxonomy
from trustmed_fabric.timeutil import ensure_utc, utcnow


def _at(anchor: datetime, days_ago: int, hour: int = 9) -> datetime:
    base = anchor.replace(hour=hour, minute=0, second=0, microsecond=0)
    return base - timedelta(days=days_ago)


def _date(value: str) -> date:
    return date.fromisoformat(value)


def _approval(config: dict[str, Any] | None, version: int, anchor: datetime) -> Approval | None:
    if config is None:
        return None
    approved_at = _at(anchor, int(config["approved_days_ago"]), hour=14)
    expires_at = anchor.replace(hour=14, minute=0, second=0, microsecond=0) + timedelta(
        days=int(config["expires_in_days"])
    )
    return Approval(
        status=ApprovalStatus(config["status"]),
        material_id=config["material_id"],
        approved_by=config["approved_by"],
        review_board=config["review_board"],
        approved_at=approved_at,
        expires_at=expires_at,
        version=version,
    )


def load_taxonomy() -> Taxonomy:
    from trustmed_fabric.fixtures import taxonomy_pack

    pack = taxonomy_pack()
    return Taxonomy(
        version=str(pack["version"]),
        terms=[TaxonomyTerm.model_validate(item) for item in pack["terms"]],
    )


def seed_store(store: Store, *, now: datetime | None = None, reset: bool = False) -> dict[str, Any]:
    anchor = ensure_utc(now or utcnow())
    if store.count("asset") and not reset:
        return {
            "seeded": False,
            "reason": "database already contains assets",
            "assets": store.count("asset"),
        }
    if reset:
        store.reset()

    content = content_pack()
    pack = seed_pack()

    evidence = [Evidence.model_validate(item) for item in content["evidence"]]
    claims = [
        Claim.model_validate(
            {
                **item,
                "reviewed_at": _date(item["reviewed_at"]),
            }
        )
        for item in content["claims"]
    ]
    assets: list[Asset] = []
    for item in content["assets"]:
        created_at = _at(anchor, int(item["created_days_ago"]), hour=9)
        approval = _approval(item.get("approval"), int(item["version"]), anchor)
        updated_at = max(created_at, approval.approved_at) if approval else created_at
        assets.append(
            Asset.model_validate(
                {
                    **{
                        k: v
                        for k, v in item.items()
                        if k not in {"created_days_ago", "approval"}
                    },
                    "approval": approval,
                    "created_at": created_at,
                    "updated_at": updated_at,
                    "metadata": {
                        "synthetic": True,
                        "connector": item["source_system"],
                        "data_pack": content["dataset"]["version"],
                    },
                }
            )
        )

    experiences = [
        Experience.model_validate(
            {
                **{k: v for k, v in item.items() if k != "launched_days_ago"},
                "launched_at": _at(anchor, int(item["launched_days_ago"]), hour=8),
            }
        )
        for item in pack["experiences"]
    ]
    asset_by_id = {asset.id: asset for asset in assets}
    experience_by_id = {experience.id: experience for experience in experiences}

    publications: list[Publication] = []
    metrics: list[Metric] = []
    metric_ids_by_publication: dict[str, list[str]] = {}
    for item in pack["publications"]:
        asset = asset_by_id[item["asset_id"]]
        experience = experience_by_id[item["experience_id"]]
        published_at = _at(anchor, int(item["days_ago"]), hour=11)
        publication = Publication(
            id=item["id"],
            asset_id=asset.id,
            asset_version=asset.version,
            experience_id=experience.id,
            channel=experience.channel,
            market=experience.market,
            destination=item["destination"],
            external_id=item["external_id"],
            published_at=published_at,
            content_hash=asset.content_hash,
            status=PublicationStatus(item["status"]),
        )
        publications.append(publication)
        config = item.get("metrics")
        if config is None:
            continue
        generated = _generate_metrics(publication, experience, config, anchor)
        metrics.extend(generated)
        metric_ids_by_publication[publication.id] = [metric.id for metric in generated]

    publication_by_id = {publication.id: publication for publication in publications}
    insights: list[Insight] = []
    for item in pack["insights"]:
        publication = publication_by_id[item["publication_id"]]
        metric_ids = metric_ids_by_publication.get(publication.id, [])
        if not metric_ids:
            continue
        generated_at = _at(anchor, int(item["generated_days_ago"]), hour=16)
        insights.append(
            Insight(
                id=item["id"],
                experience_id=publication.experience_id,
                publication_id=publication.id,
                title=item["title"],
                finding=item["finding"],
                recommendation=item["recommendation"],
                metric_ids=metric_ids,
                confidence=float(item["confidence"]),
                generated_at=generated_at,
            )
        )

    store.put_many("evidence", evidence)
    store.put_many("claim", claims)
    store.put_many("asset", assets)
    store.put_many("experience", experiences)
    store.put_many("publication", publications)
    store.put_many("metric", metrics)
    store.put_many("insight", insights)

    event_specs: list[dict[str, Any]] = []

    for item in evidence:
        event_specs.append(
            {
                "occurred_at": datetime.combine(item.effective_at, time(9, 0), tzinfo=UTC),
                "priority": 0,
                "event_type": "evidence.registered",
                "subject_type": "evidence",
                "subject_id": item.id,
                "actor": "evidence-library",
                "payload": {
                    "title": item.title,
                    "type": item.evidence_type.value,
                    "markets": [m.value for m in item.markets],
                    "expires_at": item.expires_at.isoformat(),
                },
                "edges": [],
            }
        )
    for claim in claims:
        event_specs.append(
            {
                "occurred_at": datetime.combine(claim.reviewed_at, time(10, 0), tzinfo=UTC),
                "priority": 1,
                "event_type": "claim.approved" if claim.status is ClaimStatus.APPROVED else "claim.recorded",
                "subject_type": "claim",
                "subject_id": claim.id,
                "actor": "medical-review",
                "payload": {
                    "status": claim.status.value,
                    "markets": [m.value for m in claim.markets],
                    "type": claim.claim_type.value,
                },
                "edges": [
                    {
                        "source": node_id("claim", claim.id),
                        "target": node_id("evidence", evidence_id),
                        "relation": "supported_by",
                    }
                    for evidence_id in claim.evidence_ids
                ],
            }
        )
    for asset in assets:
        event_specs.append(
            {
                "occurred_at": asset.created_at,
                "priority": 2,
                "event_type": "asset.created",
                "subject_type": "asset",
                "subject_id": asset.id,
                "actor": asset.owner,
                "payload": {
                    "title": asset.title,
                    "version": asset.version,
                    "status": asset.status.value,
                    "content_hash": asset.content_hash,
                    "market": asset.market.value,
                    "audience": asset.audience.value,
                },
                "edges": [
                    {
                        "source": node_id("asset", asset.id),
                        "target": node_id("claim", claim_id),
                        "relation": "asserts",
                    }
                    for claim_id in asset.claim_ids
                ],
            }
        )
        if asset.approval is not None:
            event_specs.append(
                {
                    "occurred_at": asset.approval.approved_at,
                    "priority": 3,
                    "event_type": "asset.approved",
                    "subject_type": "asset",
                    "subject_id": asset.id,
                    "actor": asset.approval.review_board,
                    "payload": {
                        "material_id": asset.approval.material_id,
                        "version": asset.approval.version,
                        "approved_by": asset.approval.approved_by,
                        "expires_at": asset.approval.expires_at.isoformat(),
                        "content_hash": asset.content_hash,
                    },
                    "edges": [],
                }
            )
    for experience in experiences:
        event_specs.append(
            {
                "occurred_at": experience.launched_at,
                "priority": 0,
                "event_type": "experience.launched",
                "subject_type": "experience",
                "subject_id": experience.id,
                "actor": experience.owner,
                "payload": {
                    "channel": experience.channel.value,
                    "market": experience.market.value,
                    "surface_version": experience.surface_version,
                    "status": experience.status.value,
                },
                "edges": [],
            }
        )
    for publication in publications:
        asset = asset_by_id[publication.asset_id]
        event_specs.append(
            {
                "occurred_at": publication.published_at,
                "priority": 4,
                "event_type": "asset.published",
                "subject_type": "publication",
                "subject_id": publication.id,
                "actor": publication.actor,
                "payload": {
                    "asset_id": publication.asset_id,
                    "asset_version": publication.asset_version,
                    "content_hash": publication.content_hash,
                    "external_id": publication.external_id,
                    "destination": publication.destination,
                    "asset_title": asset.title,
                },
                "edges": [
                    {
                        "source": node_id("asset", publication.asset_id),
                        "target": node_id("publication", publication.id),
                        "relation": "published_as",
                    },
                    {
                        "source": node_id("publication", publication.id),
                        "target": node_id("experience", publication.experience_id),
                        "relation": "delivered_in",
                    },
                ],
            }
        )
    metrics_by_publication: dict[str, list[Metric]] = {}
    for metric in metrics:
        metrics_by_publication.setdefault(metric.publication_id, []).append(metric)
    for publication_id, rows in metrics_by_publication.items():
        latest = max(row.metric_date for row in rows)
        event_specs.append(
            {
                "occurred_at": datetime.combine(latest, time(23, 0), tzinfo=UTC),
                "priority": 5,
                "event_type": "metrics.captured",
                "subject_type": "measurement",
                "subject_id": publication_id,
                "actor": "measurement-pipeline",
                "payload": {
                    "publication_id": publication_id,
                    "metric_ids": [row.id for row in rows],
                    "impressions": sum(row.impressions for row in rows),
                    "engagements": sum(row.engagements for row in rows),
                    "conversions": sum(row.conversions for row in rows),
                },
                "edges": [
                    {
                        "source": node_id("experience", row.experience_id),
                        "target": node_id("metric", row.id),
                        "relation": "measured_by",
                    }
                    for row in rows
                ],
            }
        )
    for insight in insights:
        event_specs.append(
            {
                "occurred_at": insight.generated_at,
                "priority": 6,
                "event_type": "insight.generated",
                "subject_type": "insight",
                "subject_id": insight.id,
                "actor": "insight-service",
                "payload": {
                    "title": insight.title,
                    "confidence": insight.confidence,
                    "publication_id": insight.publication_id,
                },
                "edges": [
                    {
                        "source": node_id("metric", metric_id),
                        "target": node_id("insight", insight.id),
                        "relation": "informs",
                    }
                    for metric_id in insight.metric_ids
                ],
            }
        )

    event_specs.sort(
        key=lambda event: (
            event["occurred_at"],
            event["priority"],
            event["subject_type"],
            event["subject_id"],
        )
    )
    previous = None
    for sequence, spec in enumerate(event_specs, start=1):
        previous = store.append_event(
            event_type=spec["event_type"],
            subject_type=spec["subject_type"],
            subject_id=spec["subject_id"],
            actor=spec["actor"],
            payload=spec["payload"],
            edges=spec["edges"],
            occurred_at=spec["occurred_at"],
            trace_id=f"trc_seed_{sequence:04d}",
            event_id=f"evt_seed_{sequence:04d}",
        )
    verification = store.verify_ledger()
    if not verification["valid"]:  # pragma: no cover - defensive
        raise RuntimeError(f"seeded ledger failed verification: {verification['reason']}")
    return {
        "seeded": True,
        "anchor": anchor.isoformat(),
        "assets": len(assets),
        "claims": len(claims),
        "evidence": len(evidence),
        "experiences": len(experiences),
        "publications": len(publications),
        "metrics": len(metrics),
        "insights": len(insights),
        "ledger_events": store.event_count(),
        "ledger_head": previous.hash if previous else None,
        "counts": store.table_counts(),
    }


def ensure_seeded(store: Store, *, now: datetime | None = None) -> dict[str, Any]:
    if store.count("asset") > 0:
        return {"seeded": False, "assets": store.count("asset")}
    return seed_store(store, now=now)


def _generate_metrics(
    publication: Publication,
    experience: Experience,
    config: dict[str, Any],
    anchor: datetime,
) -> list[Metric]:
    weeks = int(config["weeks"])
    total_impressions = int(config["impressions"])
    per_week = max(1, total_impressions // weeks)
    rng = random.Random(f"{publication.id}:{anchor.date().isoformat()}")
    rows: list[Metric] = []
    quality = 0.71 if experience.surface_version == "ads-2025.4" else round(
        rng.uniform(0.93, 0.99), 2
    )
    for week in range(1, weeks + 1):
        metric_date = (publication.published_at + timedelta(days=7 * week)).date()
        if metric_date > anchor.date():
            break
        impressions = int(per_week * rng.uniform(0.88, 1.12))
        engagements = min(impressions, int(impressions * config["engagement_rate"] * rng.uniform(0.94, 1.06)))
        conversions = min(
            engagements,
            max(1, int(engagements * config["conversion_rate"] * rng.uniform(0.9, 1.1))),
        )
        rows.append(
            Metric(
                id=f"MET-{publication.id}-W{week:02d}",
                experience_id=experience.id,
                publication_id=publication.id,
                metric_date=metric_date,
                impressions=impressions,
                engagements=engagements,
                conversions=conversions,
                source_system="measurement-hub",
                attribution_model="last_touch_demo",
                consent_basis=(
                    "explicit_opt_in" if experience.consent_required else "legitimate_interest"
                ),
                quality_score=quality,
            )
        )
    return rows


def dataset_profile(store: Store, *, now: datetime | None = None) -> dict[str, Any]:
    anchor = ensure_utc(now or utcnow())
    assets = store.list_models("asset", Asset)
    counts = Counter(asset.status.value for asset in assets)
    return {
        "as_of": anchor.isoformat(),
        "assets": len(assets),
        "status_counts": dict(sorted(counts.items())),
        "markets": sorted({asset.market.value for asset in assets}),
        "audiences": sorted({asset.audience.value for asset in assets}),
        "publications": store.count("publication"),
        "experiences": store.count("experience"),
        "metrics": store.count("metric"),
        "insights": store.count("insight"),
    }
