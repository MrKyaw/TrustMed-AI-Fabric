"""Operator CLI for seeding, querying, evaluating and serving the fabric."""

from __future__ import annotations

import argparse
import json
import sys
from datetime import UTC, datetime
from typing import Any

from trustmed_fabric.evals import render_markdown
from trustmed_fabric.lineage import governance_gaps
from trustmed_fabric.models import AskRequest, Audience, Channel, Market
from trustmed_fabric.seed import seed_store
from trustmed_fabric.service import FabricService
from trustmed_fabric.settings import Settings
from trustmed_fabric.store import Store


def _service(settings: Settings) -> FabricService:
    store = Store(settings.db_path)
    return FabricService(
        store,
        auto_seed=settings.auto_seed,
        report_path=settings.report_path,
        now=datetime.now(UTC),
    )


def _print(value: Any, as_json: bool = True) -> None:
    if as_json:
        print(json.dumps(value, indent=2, ensure_ascii=False, default=str))
    else:
        print(value)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="trustmed",
        description="TrustMed AI Fabric - governed life-sciences content platform",
    )
    parser.add_argument("--db", default=None, help="override the SQLite database path")
    sub = parser.add_subparsers(dest="command", required=True)

    seed = sub.add_parser("seed", help="create the synthetic dataset")
    seed.add_argument("--reset", action="store_true", help="delete existing data first")

    serve = sub.add_parser("serve", help="run the API and operator console")
    serve.add_argument("--host", default=None)
    serve.add_argument("--port", type=int, default=None)

    ask = sub.add_parser("ask", help="ask the governed assistant")
    ask.add_argument("question")
    ask.add_argument("--market", default="US", choices=[m.value for m in Market])
    ask.add_argument(
        "--audience", default="HCP", choices=[a.value for a in Audience]
    )
    ask.add_argument("--channel", default=None, choices=[c.value for c in Channel])
    ask.add_argument("--json", action="store_true")

    trace = sub.add_parser("trace", help="show an asset's lineage graph")
    trace.add_argument("asset_id")

    evaluate = sub.add_parser("evaluate", help="evaluate an asset against policy")
    evaluate.add_argument("asset_id")
    evaluate.add_argument("--market", default="US", choices=[m.value for m in Market])
    evaluate.add_argument("--audience", default="HCP", choices=[a.value for a in Audience])
    evaluate.add_argument("--channel", default="WEB", choices=[c.value for c in Channel])
    evaluate.add_argument("--experience", default=None)

    eval_cmd = sub.add_parser("eval", help="run the golden evaluation set and quality gate")
    eval_cmd.add_argument("--json", action="store_true")
    eval_cmd.add_argument("--no-write", action="store_true")

    gaps = sub.add_parser("gaps", help="list cross-team governance gaps")
    gaps.add_argument("--json", action="store_true")

    audit = sub.add_parser("audit", help="verify or export the audit ledger")
    audit_sub = audit.add_subparsers(dest="audit_command", required=True)
    audit_sub.add_parser("verify", help="recompute the hash chain")
    export = audit_sub.add_parser("export", help="write NDJSON to a file or stdout")
    export.add_argument("--output", default=None)

    publish = sub.add_parser("publish", help="publish an approved asset to an experience")
    publish.add_argument("asset_id")
    publish.add_argument("experience_id")
    publish.add_argument("destination")
    publish.add_argument("--idempotency-key", default=None)

    sub.add_parser("claims", help="list claims and evidence links")
    sub.add_parser("policies", help="list the policy catalog")

    args = parser.parse_args(argv)
    settings = Settings.from_env()
    if args.db:
        settings = Settings(
            db_path=args.db,
            api_key=settings.api_key,
            host=settings.host,
            port=settings.port,
            report_dir=settings.report_dir,
            auto_seed=settings.auto_seed,
        )

    if args.command == "seed":
        store = Store(settings.db_path)
        result = seed_store(store, reset=args.reset)
        _print(result)
        return 0

    if args.command == "serve":
        import uvicorn

        from trustmed_fabric.api import create_app

        service = _service(settings)
        app = create_app(service=service, settings=settings)
        uvicorn.run(
            app,
            host=args.host or settings.host,
            port=args.port or settings.port,
            log_level="info",
        )
        return 0

    service = _service(settings)

    if args.command == "ask":
        response = service.ask(
            AskRequest(
                question=args.question,
                market=Market(args.market),
                audience=Audience(args.audience),
                channel=Channel(args.channel) if args.channel else None,
            )
        )
        if args.json:
            _print(response.model_dump(mode="json"))
        else:
            print(response.answer)
            print()
            print(f"trace: {response.trace_id}")
            print(f"refused: {response.refused} ({response.refusal_reason or 'no'})")
            for citation in response.citations:
                print(f"  - {citation.asset_id} v{citation.asset_version}#{citation.section_id}")
            if response.decision:
                print(f"policy: {response.decision.outcome.value} ({response.decision.score}/100)")
        return 0

    if args.command == "trace":
        graph = service.lineage(args.asset_id)
        _print(graph)
        return 0

    if args.command == "evaluate":
        decision = service.evaluate(
            args.asset_id,
            Market(args.market),
            Audience(args.audience),
            Channel(args.channel),
            experience_id=args.experience,
        )
        _print(decision.model_dump(mode="json"))
        return 0 if decision.outcome.value != "DENY" else 2

    if args.command == "eval":
        report, json_path, md_path = service.refresh_eval_report()
        if args.json:
            _print(report.model_dump(mode="json"))
        else:
            print(render_markdown(report))
            print(f"JSON: {json_path}")
            print(f"Markdown: {md_path}")
        return 0 if report.gate_passed else 1

    if args.command == "gaps":
        rows = governance_gaps(service.store, now=datetime.now(UTC))
        if args.json:
            _print(rows)
        else:
            for row in rows:
                print(f"[{row['severity']}] {row['code']} {row['subject']}: {row['message']}")
            print(f"{len(rows)} gap(s)")
        return 0

    if args.command == "audit":
        if args.audit_command == "verify":
            result = service.audit_verify()
            _print(result)
            return 0 if result["valid"] else 1
        lines = service.audit_export_lines()
        payload = "\n".join(lines) + "\n"
        if args.output:
            with open(args.output, "w", encoding="utf-8") as handle:
                handle.write(payload)
            print(f"wrote {len(lines)} events to {args.output}")
        else:
            sys.stdout.write(payload)
        return 0

    if args.command == "publish":
        result = service.publish(
            asset_id=args.asset_id,
            experience_id=args.experience_id,
            destination=args.destination,
            idempotency_key=args.idempotency_key,
        )
        _print(result)
        return 0

    if args.command == "claims":
        _print(service.list_claims())
        return 0

    if args.command == "policies":
        _print(service.policy_catalog())
        return 0

    parser.error(f"unknown command {args.command}")
    return 2
