"""Application service layer shared by HTTP, MCP and the CLI.

Keeping orchestration here means the three entry points cannot drift: they all
resolve the same policy engine, retrieval index and audit ledger.
"""

from __future__ import annotations

import hashlib
from collections import defaultdict
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from trustmed_fabric.assistant import GovernedAssistant
from trustmed_fabric.canonical import canonical_json
from trustmed_fabric.claims import ClaimRegistry
from trustmed_fabric.errors import ConflictError, NotFoundError, PolicyDeniedError, ValidationError
from trustmed_fabric.evals import EvalReport, load_report, run_evaluations, write_reports
from trustmed_fabric.lineage import (
    governance_gaps,
    node_id,
    trace_asset,
    trace_entity,
    traceability_coverage,
)
from trustmed_fabric.models import (
    AskRequest,
    AskResponse,
    Asset,
    AssetStatus,
    Audience,
    Channel,
    Claim,
    ClaimAssessment,
    Experience,
    ExperienceStatus,
    Insight,
    Market,
    Metric,
    PolicyDecision,
    PolicyOutcome,
    Publication,
    PublicationStatus,
)
from trustmed_fabric.policies import POLICY_CATALOG, PolicyEngine
from trustmed_fabric.retrieval import RetrievalIndex
from trustmed_fabric.seed import ensure_seeded, load_taxonomy
from trustmed_fabric.store import Store
from trustmed_fabric.timeutil import ensure_utc, utcnow


class FabricService:
    def __init__(
        self,
        store: Store,
        *,
        auto_seed: bool = True,
        report_path: str | Path = "reports/eval-report.json",
        now: datetime | None = None,
    ) -> None:
        self.store = store
        self.report_path = Path(report_path)
        self.anchor = ensure_utc(now or utcnow())
        if auto_seed:
            ensure_seeded(store, now=self.anchor)
        self.taxonomy = load_taxonomy()
        self.claims = ClaimRegistry(store)
        self.index = RetrievalIndex(store, self.taxonomy)
        self.policies = PolicyEngine(store, self.taxonomy, self.claims)
        self.assistant = GovernedAssistant(
            store, self.taxonomy, self.index, self.claims, self.policies
        )
        self._eval_cache: EvalReport | None = None

    # --------------------------------------------------------------------- AI

    def ask(self, request: AskRequest, *, now: datetime | None = None) -> AskResponse:
        return self.assistant.ask(request, now=now)

    def get_trace(self, trace_id: str) -> dict[str, Any]:
        trace = self.store.get_ai_trace(trace_id)
        if trace is None:
            raise NotFoundError(f"AI trace {trace_id!r} was not found")
        return trace

    # ------------------------------------------------------------------ policy

    def evaluate(
        self,
        asset_id: str,
        market: Market,
        audience: Audience,
        channel: Channel,
        experience_id: str | None = None,
        *,
        now: datetime | None = None,
        for_publication: bool = False,
    ) -> PolicyDecision:
        return self.policies.evaluate(
            asset_id,
            market,
            audience,
            channel,
            experience_id=experience_id,
            now=now or self.anchor,
            for_publication=for_publication,
        )

    def policy_catalog(self) -> list[dict[str, str]]:
        return POLICY_CATALOG

    def assess_claim(
        self, claim_id: str, market: Market, *, now: datetime | None = None
    ) -> ClaimAssessment:
        return self.claims.assess(claim_id, market, now=now or self.anchor)

    # -------------------------------------------------------------------- data

    def list_assets(
        self,
        *,
        market: Market | None = None,
        audience: Audience | None = None,
        status: AssetStatus | None = None,
        q: str | None = None,
        now: datetime | None = None,
    ) -> list[dict[str, Any]]:
        as_of = ensure_utc(now or self.anchor)
        assets = self.store.list_models("asset", Asset)
        if market is not None:
            assets = [asset for asset in assets if asset.market is market]
        if audience is not None:
            assets = [asset for asset in assets if asset.audience is audience]
        if status is not None:
            assets = [asset for asset in assets if asset.status is status]
        if q:
            needle = q.lower()
            assets = [
                asset
                for asset in assets
                if needle
                in " ".join(
                    [asset.id, asset.title, asset.summary, *asset.tags, *asset.claim_ids]
                ).lower()
            ]
        results = []
        for asset in sorted(assets, key=lambda item: item.id):
            experience = self._experience_for_asset(asset)
            decision = self.policies.evaluate(
                asset.id,
                asset.market,
                asset.audience,
                asset.channel,
                experience_id=experience.id if experience else None,
                now=as_of,
            )
            expiry_days = (
                (asset.approval.expires_at - as_of).days if asset.approval else None
            )
            results.append(
                {
                    "id": asset.id,
                    "title": asset.title,
                    "brand": asset.brand,
                    "market": asset.market.value,
                    "audience": asset.audience.value,
                    "channel": asset.channel.value,
                    "asset_type": asset.asset_type.value,
                    "status": asset.status.value,
                    "version": asset.version,
                    "summary": asset.summary,
                    "tags": asset.tags,
                    "claim_ids": asset.claim_ids,
                    "content_hash": asset.content_hash,
                    "expires_at": asset.approval.expires_at.isoformat() if asset.approval else None,
                    "expires_in_days": expiry_days,
                    "policy": {
                        "outcome": decision.outcome.value,
                        "score": decision.score,
                        "blockers": len(decision.blockers),
                    },
                }
            )
        return results

    def asset_detail(
        self, asset_id: str, *, now: datetime | None = None
    ) -> dict[str, Any]:
        as_of = ensure_utc(now or self.anchor)
        asset = self.store.get_model("asset", asset_id, Asset)
        if asset is None:
            raise NotFoundError(f"asset {asset_id!r} was not found")
        experience = self._experience_for_asset(asset)
        decision = self.policies.evaluate(
            asset.id,
            asset.market,
            asset.audience,
            asset.channel,
            experience_id=experience.id if experience else None,
            now=as_of,
        )
        graph = trace_asset(self.store, asset.id)
        publications = [
            publication
            for publication in self.store.list_models("publication", Publication)
            if publication.asset_id == asset.id
        ]
        metrics_by_publication: dict[str, list[Metric]] = defaultdict(list)
        for metric in self.store.list_models("metric", Metric):
            metrics_by_publication[metric.publication_id].append(metric)
        publication_rows = []
        for publication in publications:
            rows = metrics_by_publication.get(publication.id, [])
            experience_model = self.store.get_model("experience", publication.experience_id, Experience)
            publication_rows.append(
                {
                    **publication.model_dump(mode="json"),
                    "experience_name": experience_model.name if experience_model else None,
                    "impressions": sum(row.impressions for row in rows),
                    "engagements": sum(row.engagements for row in rows),
                    "conversions": sum(row.conversions for row in rows),
                }
            )
        assessments = []
        for claim_id in asset.claim_ids:
            try:
                assessments.append(
                    self.claims.assess(claim_id, asset.market, now=as_of).model_dump(mode="json")
                )
            except NotFoundError:
                assessments.append({"claim_id": claim_id, "allowed": False, "findings": []})
        insights = [
            insight.model_dump(mode="json")
            for insight in self.store.list_models("insight", Insight)
            if insight.publication_id in {publication.id for publication in publications}
        ]
        return {
            "asset": asset.model_dump(mode="json"),
            "content_hash": asset.content_hash,
            "policy": decision.model_dump(mode="json"),
            "lineage": {
                "counts": graph.counts,
                "gaps": graph.gaps,
                "edges": len(graph.edges),
            },
            "publications": publication_rows,
            "claims": assessments,
            "insights": insights,
            "audit_events": [
                event.model_dump(mode="json")
                for event in self.store.events(limit=12, subject_id=asset.id)
            ],
        }

    def list_claims(self) -> list[dict[str, Any]]:
        return [
            claim.model_dump(mode="json")
            for claim in sorted(
                self.store.list_models("claim", Claim), key=lambda item: item.id
            )
        ]

    def list_experiences(self) -> list[dict[str, Any]]:
        return [
            experience.model_dump(mode="json")
            for experience in sorted(
                self.store.list_models("experience", Experience), key=lambda item: item.id
            )
        ]

    def list_publications(self) -> list[dict[str, Any]]:
        assets = {
            asset.id: asset for asset in self.store.list_models("asset", Asset)
        }
        experiences = {
            experience.id: experience
            for experience in self.store.list_models("experience", Experience)
        }
        rows = []
        for publication in sorted(
            self.store.list_models("publication", Publication), key=lambda item: item.id
        ):
            rows.append(
                {
                    **publication.model_dump(mode="json"),
                    "asset_title": assets[publication.asset_id].title
                    if publication.asset_id in assets
                    else None,
                    "experience_name": experiences[publication.experience_id].name
                    if publication.experience_id in experiences
                    else None,
                }
            )
        return rows

    def taxonomy_list(self) -> list[dict[str, object]]:
        return self.taxonomy.as_list()

    # --------------------------------------------------------------- analytics

    def overview(self, *, now: datetime | None = None) -> dict[str, Any]:
        as_of = ensure_utc(now or self.anchor)
        assets = self.store.list_models("asset", Asset)
        publications = self.store.list_models("publication", Publication)
        experiences = self.store.list_models("experience", Experience)
        metrics = self.store.list_models("metric", Metric)
        insights = self.store.list_models("insight", Insight)
        approved = [
            asset
            for asset in assets
            if asset.status is AssetStatus.APPROVED
            and asset.approval
            and asset.approval.expires_at > as_of
        ]
        live_publications = [
            publication
            for publication in publications
            if publication.status is PublicationStatus.LIVE
        ]
        expiring = [
            asset
            for asset in approved
            if asset.approval
            and (asset.approval.expires_at - as_of) <= timedelta(days=30)
        ]
        coverage = traceability_coverage(self.store)
        gaps = governance_gaps(self.store, now=as_of)
        impressions = sum(metric.impressions for metric in metrics)
        engagements = sum(metric.engagements for metric in metrics)
        conversions = sum(metric.conversions for metric in metrics)
        channels: dict[str, dict[str, int]] = {}
        publication_lookup = {publication.id: publication for publication in publications}
        for metric in metrics:
            publication = publication_lookup.get(metric.publication_id)
            key = publication.channel.value if publication else "UNKNOWN"
            bucket = channels.setdefault(
                key, {"impressions": 0, "engagements": 0, "conversions": 0}
            )
            bucket["impressions"] += metric.impressions
            bucket["engagements"] += metric.engagements
            bucket["conversions"] += metric.conversions
        eval_report = self.eval_report()
        return {
            "generated_at": as_of.isoformat(),
            "kpis": {
                "approved_assets": len(approved),
                "live_publications": len(live_publications),
                "live_experiences": sum(
                    1 for experience in experiences if experience.status is ExperienceStatus.LIVE
                ),
                "traceability_coverage_pct": coverage["coverage_pct"],
                "engagement_rate_pct": round(engagements / impressions * 100, 2)
                if impressions
                else 0.0,
                "conversion_rate_pct": round(conversions / engagements * 100, 2)
                if engagements
                else 0.0,
                "open_gaps": len(gaps),
                "expiring_approvals": len(expiring),
                "eval_pass_rate": eval_report.metrics.pass_rate if eval_report else None,
                "golden_cases": eval_report.metrics.total if eval_report else 0,
            },
            "funnel": self.funnel(now=as_of),
            "coverage": coverage,
            "gaps": gaps,
            "channels": [
                {"channel": channel, **values}
                for channel, values in sorted(channels.items())
            ],
            "recent_events": [
                self._event_summary(event)
                for event in self.store.events(limit=10)
            ],
            "metadata": {
                "assets": len(assets),
                "publications": len(publications),
                "metrics": len(metrics),
                "insights": len(insights),
                "ledger_events": self.store.event_count(),
                "taxonomy_version": self.taxonomy.version,
                "eval_gate_passed": eval_report.gate_passed if eval_report else None,
            },
        }

    def funnel(
        self, *, market: Market | None = None, now: datetime | None = None
    ) -> dict[str, Any]:
        as_of = ensure_utc(now or self.anchor)
        assets = self.store.list_models("asset", Asset)
        publications = self.store.list_models("publication", Publication)
        experiences = {
            experience.id: experience
            for experience in self.store.list_models("experience", Experience)
        }
        metrics = self.store.list_models("metric", Metric)
        insights = self.store.list_models("insight", Insight)
        if market is not None:
            assets = [asset for asset in assets if asset.market is market]
            publications = [
                publication for publication in publications if publication.market is market
            ]
        publication_ids = {publication.id for publication in publications}
        metrics = [metric for metric in metrics if metric.publication_id in publication_ids]
        insights = [
            insight for insight in insights if insight.publication_id in publication_ids
        ]
        eligible_assets = [
            asset
            for asset in assets
            if asset.status is AssetStatus.APPROVED
            and asset.approval
            and asset.approval.expires_at > as_of
        ]
        live_publications = [
            publication
            for publication in publications
            if publication.status is PublicationStatus.LIVE
        ]
        live_experience_ids = {
            publication.experience_id
            for publication in live_publications
            if publication.experience_id in experiences
            and experiences[publication.experience_id].status is ExperienceStatus.LIVE
        }
        measured_publications = {metric.publication_id for metric in metrics}
        impressions = sum(metric.impressions for metric in metrics)
        engagements = sum(metric.engagements for metric in metrics)
        conversions = sum(metric.conversions for metric in metrics)
        stages = [
            {"stage": "Approved assets", "value": len(eligible_assets), "unit": "assets"},
            {"stage": "Live publications", "value": len(live_publications), "unit": "placements"},
            {"stage": "Live experiences", "value": len(live_experience_ids), "unit": "experiences"},
            {"stage": "Impressions", "value": impressions, "unit": "impressions"},
            {"stage": "Engagements", "value": engagements, "unit": "engagements"},
            {"stage": "Qualified actions", "value": conversions, "unit": "conversions"},
            {"stage": "Documented insights", "value": len(insights), "unit": "insights"},
        ]
        return {
            "market": market.value if market else "ALL",
            "stages": stages,
            "measured_publications": len(measured_publications),
            "unmeasured_publications": len(
                [p for p in live_publications if p.id not in measured_publications]
            ),
            "traceability_pct": round(
                len(measured_publications.intersection({p.id for p in live_publications}))
                / len(live_publications)
                * 100,
                1,
            )
            if live_publications
            else 100.0,
        }

    def insights(self) -> list[dict[str, Any]]:
        assets = {asset.id: asset for asset in self.store.list_models("asset", Asset)}
        publications = {
            publication.id: publication
            for publication in self.store.list_models("publication", Publication)
        }
        experiences = {
            experience.id: experience
            for experience in self.store.list_models("experience", Experience)
        }
        metrics: dict[str, list[Metric]] = defaultdict(list)
        for metric in self.store.list_models("metric", Metric):
            metrics[metric.publication_id].append(metric)
        rows = []
        for insight in sorted(
            self.store.list_models("insight", Insight),
            key=lambda item: item.generated_at,
            reverse=True,
        ):
            publication = publications.get(insight.publication_id)
            experience = experiences.get(insight.experience_id)
            asset = assets.get(publication.asset_id) if publication else None
            rows_metrics = metrics.get(insight.publication_id, [])
            rows.append(
                {
                    **insight.model_dump(mode="json"),
                    "asset_id": asset.id if asset else None,
                    "asset_title": asset.title if asset else None,
                    "experience_name": experience.name if experience else None,
                    "market": publication.market.value if publication else None,
                    "channel": publication.channel.value if publication else None,
                    "impressions": sum(row.impressions for row in rows_metrics),
                    "engagements": sum(row.engagements for row in rows_metrics),
                    "conversions": sum(row.conversions for row in rows_metrics),
                }
            )
        return rows

    # -------------------------------------------------------------- publishing

    def publish(
        self,
        *,
        asset_id: str,
        experience_id: str,
        destination: str,
        idempotency_key: str | None = None,
        now: datetime | None = None,
    ) -> dict[str, Any]:
        as_of = ensure_utc(now or self.anchor)
        request_payload = {
            "asset_id": asset_id,
            "experience_id": experience_id,
            "destination": destination,
        }
        operation = hashlib.sha256(canonical_json(request_payload).encode()).hexdigest()
        if idempotency_key:
            existing = self.store.get_idempotent(idempotency_key)
            if existing is not None:
                if existing["operation"] != operation:
                    raise ConflictError(
                        "the idempotency key was already used for a different publication request"
                    )
                return {**existing["response"], "idempotent_replay": True}
        asset = self.store.get_model("asset", asset_id, Asset)
        if asset is None:
            raise NotFoundError(f"asset {asset_id!r} was not found")
        experience = self.store.get_model("experience", experience_id, Experience)
        if experience is None:
            raise NotFoundError(f"experience {experience_id!r} was not found")
        if not destination.startswith("https://"):
            raise ValidationError("destination must be an https:// URL")
        decision = self.policies.evaluate(
            asset.id,
            experience.market,
            experience.audience,
            experience.channel,
            experience_id=experience.id,
            now=as_of,
            for_publication=True,
        )
        if decision.outcome is PolicyOutcome.DENY:
            raise PolicyDeniedError(
                "publication blocked by policy",
                details={"decision": decision.model_dump(mode="json")},
            )
        existing_ids = [
            publication.id for publication in self.store.list_models("publication", Publication)
        ]
        next_number = max(
            [int(publication_id.split("-")[-1]) for publication_id in existing_ids] or [0]
        ) + 1
        publication = Publication(
            id=f"PUB-{next_number:03d}",
            asset_id=asset.id,
            asset_version=asset.version,
            experience_id=experience.id,
            channel=experience.channel,
            market=experience.market,
            destination=destination,
            external_id=f"api-{asset.id.lower()}-{next_number:03d}",
            published_at=as_of,
            content_hash=asset.content_hash,
            status=PublicationStatus.LIVE,
            actor="publisher-service",
        )
        self.store.put("publication", publication)
        event = self.store.append_event(
            event_type="asset.published",
            subject_type="publication",
            subject_id=publication.id,
            actor="publisher-service",
            occurred_at=as_of,
            payload={
                "asset_id": asset.id,
                "asset_version": asset.version,
                "content_hash": asset.content_hash,
                "external_id": publication.external_id,
                "destination": destination,
                "policy_outcome": decision.outcome.value,
            },
            edges=[
                {
                    "source": node_id("asset", asset.id),
                    "target": node_id("publication", publication.id),
                    "relation": "published_as",
                },
                {
                    "source": node_id("publication", publication.id),
                    "target": node_id("experience", experience.id),
                    "relation": "delivered_in",
                },
            ],
        )
        response = {
            "publication": publication.model_dump(mode="json"),
            "decision": decision.model_dump(mode="json"),
            "ledger_event_id": event.id,
            "idempotent_replay": False,
        }
        if idempotency_key:
            self.store.put_idempotent(idempotency_key, operation, response, 201)
        return response

    # ------------------------------------------------------------------- audit

    def audit_events(
        self, *, limit: int = 50, after_sequence: int = 0, subject_id: str | None = None
    ) -> list[dict[str, Any]]:
        return [
            self._event_summary(event)
            for event in self.store.events(
                limit=limit, after_sequence=after_sequence, subject_id=subject_id
            )
        ]

    def audit_verify(self) -> dict[str, Any]:
        return self.store.verify_ledger()

    def audit_export_lines(self) -> list[str]:
        return [
            canonical_json(event.model_dump(mode="json"))
            for event in self.store.all_events_ascending()
        ]

    def lineage(self, asset_id: str) -> dict[str, Any]:
        return trace_asset(self.store, asset_id).model_dump(mode="json")

    def entity_lineage(self, entity_type: str, entity_id: str) -> dict[str, Any]:
        return trace_entity(self.store, entity_type, entity_id).model_dump(mode="json")

    @staticmethod
    def _event_summary(event: Any) -> dict[str, Any]:
        return {
            "sequence": event.sequence,
            "id": event.id,
            "event_type": event.event_type,
            "subject_type": event.subject_type,
            "subject_id": event.subject_id,
            "occurred_at": event.occurred_at.isoformat(),
            "actor": event.actor,
            "trace_id": event.trace_id,
            "hash": event.hash,
            "prev_hash": event.prev_hash,
            "payload": event.payload,
        }

    # ------------------------------------------------------------------ evals

    def eval_report(self, *, refresh: bool = False) -> EvalReport | None:
        if self._eval_cache is not None and not refresh:
            return self._eval_cache
        if not refresh:
            loaded = load_report(self.report_path)
            if loaded is not None:
                self._eval_cache = loaded
                return loaded
        report = run_evaluations(self.assistant, as_of=self.anchor)
        self._eval_cache = report
        return report

    def refresh_eval_report(self) -> tuple[EvalReport, Path, Path]:
        report = run_evaluations(self.assistant, as_of=self.anchor)
        self._eval_cache = report
        json_path, md_path = write_reports(report, self.report_path.parent)
        return report, json_path, md_path

    # ----------------------------------------------------------------- helpers

    def _experience_for_asset(self, asset: Asset) -> Experience | None:
        for experience in self.store.list_models("experience", Experience):
            if (
                experience.market is asset.market
                and experience.audience is asset.audience
                and experience.channel is asset.channel
                and experience.status is ExperienceStatus.LIVE
            ):
                return experience
        return None
