"""A dependency-free Model Context Protocol server over stdio and HTTP.

Only governed, read-oriented tools are exposed. There is deliberately no
"publish" or "approve" tool: an agent may inspect, evaluate and retrieve, but
a human workflow must authorise distribution.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any

from pydantic import ValidationError

from trustmed_fabric import __version__
from trustmed_fabric.errors import FabricError
from trustmed_fabric.models import AskRequest, Audience, Channel, Market
from trustmed_fabric.retrieval import SearchFilters
from trustmed_fabric.service import FabricService
from trustmed_fabric.settings import Settings, build_store

PROTOCOL_VERSION = "2025-06-18"
SUPPORTED_PROTOCOLS = {"2025-06-18", "2025-03-26", "2024-11-05"}

MARKETS = ["US", "CA", "UK", "DE", "FR"]
AUDIENCES = ["HCP", "PATIENT", "CAREGIVER"]
CHANNELS = ["WEB", "EMAIL", "PAID_MEDIA", "DETAIL_AID", "FIELD", "SOCIAL"]

TOOLS: list[dict[str, Any]] = [
    {
        "name": "search_approved_content",
        "description": (
            "Search current, approved life-sciences content by market, audience and channel. "
            "Expired, draft and retired assets are excluded before ranking. Returns cited "
            "passages with approval metadata and content hashes."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "minLength": 3, "maxLength": 300},
                "market": {"type": "string", "enum": MARKETS},
                "audience": {"type": "string", "enum": AUDIENCES},
                "channel": {"type": "string", "enum": CHANNELS},
                "limit": {"type": "integer", "minimum": 1, "maximum": 8},
            },
            "required": ["query", "market", "audience"],
            "additionalProperties": False,
        },
        "annotations": {"readOnlyHint": True, "openWorldHint": False},
    },
    {
        "name": "get_content_lineage",
        "description": (
            "Trace an approved asset through claims, evidence, publications, experiences, "
            "measurements and insights. Returns the nodes, edges and any broken links."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {"asset_id": {"type": "string"}},
            "required": ["asset_id"],
            "additionalProperties": False,
        },
        "annotations": {"readOnlyHint": True, "openWorldHint": False},
    },
    {
        "name": "evaluate_content_policy",
        "description": (
            "Evaluate an asset against approval, market fit, taxonomy, claim, fair-balance, "
            "consent, privacy and partner-surface policies. Returns ALLOW, REVIEW or DENY with "
            "remediation for every finding."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "asset_id": {"type": "string"},
                "market": {"type": "string", "enum": MARKETS},
                "audience": {"type": "string", "enum": AUDIENCES},
                "channel": {"type": "string", "enum": CHANNELS},
                "experience_id": {"type": "string"},
            },
            "required": ["asset_id", "market", "audience", "channel"],
            "additionalProperties": False,
        },
        "annotations": {"readOnlyHint": True, "openWorldHint": False},
    },
    {
        "name": "check_claim",
        "description": (
            "Check whether a claim is approved for a market and whether its evidence is present, "
            "in date and applicable. Returns findings and the substantiation record."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "claim_id": {"type": "string"},
                "market": {"type": "string", "enum": MARKETS},
            },
            "required": ["claim_id", "market"],
            "additionalProperties": False,
        },
        "annotations": {"readOnlyHint": True, "openWorldHint": False},
    },
    {
        "name": "get_campaign_insights",
        "description": (
            "Return documented insights with their publication, experience, asset and "
            "measurement totals, preserving the path from content to result."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {"market": {"type": "string", "enum": MARKETS}},
            "additionalProperties": False,
        },
        "annotations": {"readOnlyHint": True, "openWorldHint": False},
    },
    {
        "name": "ask_governed_assistant",
        "description": (
            "Ask the governed assistant a question. Answers are extractive, cited, bounded to "
            "current approvals and pass input and output guardrails. Refusals include a stable "
            "reason code and are recorded in the hash-chained audit ledger."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "question": {"type": "string", "minLength": 5, "maxLength": 500},
                "market": {"type": "string", "enum": MARKETS},
                "audience": {"type": "string", "enum": AUDIENCES},
                "channel": {"type": "string", "enum": CHANNELS},
            },
            "required": ["question", "market", "audience"],
            "additionalProperties": False,
        },
        "annotations": {"readOnlyHint": True, "openWorldHint": False},
    },
    {
        "name": "get_audit_manifest",
        "description": (
            "Return ledger integrity, event count, chain head and recent audit events. Use this "
            "to prove that the lineage and AI trace have not been altered."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {"limit": {"type": "integer", "minimum": 1, "maximum": 100}},
            "additionalProperties": False,
        },
        "annotations": {"readOnlyHint": True, "openWorldHint": False},
    },
]


def _market(value: Any) -> Market:
    return Market(str(value).upper())


def _audience(value: Any) -> Audience:
    return Audience(str(value).upper())


def _channel(value: Any) -> Channel | None:
    return None if value in (None, "") else Channel(str(value).upper())


def _tool_search(service: FabricService, args: dict[str, Any]) -> dict[str, Any]:
    _require(args, "query", str)
    market = _market(_required(args, "market"))
    audience = _audience(_required(args, "audience"))
    channel = _channel(args.get("channel"))
    limit = int(args.get("limit", 4))
    if not 1 <= limit <= 8:
        raise ValueError("limit must be between 1 and 8")
    result = service.index.search(
        args["query"],
        SearchFilters(market=market, audience=audience, channel=channel, as_of=service.anchor),
        limit=limit,
    )
    return {
        "passages": [passage.model_dump(mode="json") for passage in result.passages],
        "eligible_assets": result.eligible_assets,
        "matched_assets": result.matched_assets,
        "index_version": result.index_version,
    }


def _tool_lineage(service: FabricService, args: dict[str, Any]) -> dict[str, Any]:
    return service.lineage(str(_required(args, "asset_id")))


def _tool_policy(service: FabricService, args: dict[str, Any]) -> dict[str, Any]:
    decision = service.evaluate(
        str(_required(args, "asset_id")),
        _market(_required(args, "market")),
        _audience(_required(args, "audience")),
        _channel(_required(args, "channel")) or Channel.WEB,
        experience_id=args.get("experience_id"),
    )
    return decision.model_dump(mode="json")


def _tool_claim(service: FabricService, args: dict[str, Any]) -> dict[str, Any]:
    assessment = service.assess_claim(
        str(_required(args, "claim_id")), _market(_required(args, "market"))
    )
    return assessment.model_dump(mode="json")


def _tool_insights(service: FabricService, args: dict[str, Any]) -> dict[str, Any]:
    market = None if args.get("market") in (None, "") else _market(args["market"])
    rows = service.insights()
    if market is not None:
        rows = [row for row in rows if row.get("market") == market.value]
    return {"insights": rows, "count": len(rows)}


def _tool_ask(service: FabricService, args: dict[str, Any]) -> dict[str, Any]:
    request = AskRequest(
        question=str(_required(args, "question")),
        market=_market(_required(args, "market")),
        audience=_audience(_required(args, "audience")),
        channel=_channel(args.get("channel")),
    )
    return service.ask(request).model_dump(mode="json")


def _tool_audit(service: FabricService, args: dict[str, Any]) -> dict[str, Any]:
    limit = int(args.get("limit", 20))
    if not 1 <= limit <= 100:
        raise ValueError("limit must be between 1 and 100")
    return {
        "verification": service.audit_verify(),
        "counts": service.store.table_counts(),
        "events": service.audit_events(limit=limit),
    }


HANDLERS: dict[str, Callable[[FabricService, dict[str, Any]], dict[str, Any]]] = {
    "search_approved_content": _tool_search,
    "get_content_lineage": _tool_lineage,
    "evaluate_content_policy": _tool_policy,
    "check_claim": _tool_claim,
    "get_campaign_insights": _tool_insights,
    "ask_governed_assistant": _tool_ask,
    "get_audit_manifest": _tool_audit,
}


def _required(args: dict[str, Any], key: str) -> Any:
    if key not in args or args[key] in (None, ""):
        raise ValueError(f"missing required argument {key!r}")
    return args[key]


def _require(args: dict[str, Any], key: str, expected: type) -> None:
    if not isinstance(args.get(key), expected):
        raise ValueError(f"argument {key!r} must be a {expected.__name__}")


def dispatch(payload: Any, service: FabricService) -> dict[str, Any] | None:
    if not isinstance(payload, dict):
        return _error(None, -32600, "invalid JSON-RPC request")
    request_id = payload.get("id")
    method = payload.get("method")
    if not isinstance(method, str):
        return _error(request_id, -32600, "request method must be a string")
    params = payload.get("params") or {}

    if method.startswith("notifications/"):
        return None
    if method == "initialize":
        requested = params.get("protocolVersion") if isinstance(params, dict) else None
        version = requested if requested in SUPPORTED_PROTOCOLS else PROTOCOL_VERSION
        return _result(
            request_id,
            {
                "protocolVersion": version,
                "capabilities": {"tools": {"listChanged": False}},
                "serverInfo": {
                    "name": "trustmed-ai-fabric",
                    "version": __version__,
                    "title": "TrustMed AI Fabric",
                },
                "instructions": (
                    "Governed life-sciences content retrieval. All answers are limited to current "
                    "approvals and every answer is written to the audit ledger."
                ),
            },
        )
    if method == "ping":
        return _result(request_id, {})
    if method == "tools/list":
        return _result(request_id, {"tools": TOOLS})
    if method == "resources/list":
        return _result(request_id, {"resources": []})
    if method == "prompts/list":
        return _result(request_id, {"prompts": []})
    if method == "tools/call":
        if not isinstance(params, dict):
            return _error(request_id, -32602, "params must be an object")
        name = params.get("name")
        arguments = params.get("arguments") or {}
        if not isinstance(arguments, dict):
            return _error(request_id, -32602, "tool arguments must be an object")
        handler = HANDLERS.get(str(name))
        if handler is None:
            return _error(request_id, -32602, f"unknown tool {name!r}")
        try:
            result = handler(service, arguments)
        except (FabricError, ValueError, TypeError, KeyError, ValidationError) as exc:
            message = exc.message if isinstance(exc, FabricError) else str(exc)
            return _result(
                request_id,
                {
                    "content": [{"type": "text", "text": f"Tool error: {message}"}],
                    "isError": True,
                },
            )
        return _result(
            request_id,
            {
                "content": [
                    {"type": "text", "text": json.dumps(result, indent=2, ensure_ascii=False)}
                ],
                "structuredContent": result,
                "isError": False,
            },
        )
    return _error(request_id, -32601, f"method not found: {method}")


def _result(request_id: Any, result: dict[str, Any]) -> dict[str, Any]:
    return {"jsonrpc": "2.0", "id": request_id, "result": result}


def _error(request_id: Any, code: int, message: str) -> dict[str, Any]:
    return {"jsonrpc": "2.0", "id": request_id, "error": {"code": code, "message": message}}


def handle_line(line: str, service: FabricService) -> dict[str, Any] | None:
    try:
        payload = json.loads(line)
    except json.JSONDecodeError:
        return _error(None, -32700, "parse error")
    return dispatch(payload, service)


def build_service(db_path: str | None = None) -> FabricService:
    settings = Settings.from_env()
    store = build_store(
        Settings(
            db_path=db_path or settings.db_path,
            api_key=settings.api_key,
            host=settings.host,
            port=settings.port,
            report_dir=settings.report_dir,
            auto_seed=settings.auto_seed,
        )
    )
    return FabricService(
        store,
        auto_seed=settings.auto_seed,
        report_path=settings.report_path,
        now=datetime.now(UTC),
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="TrustMed AI Fabric MCP server (stdio)")
    parser.add_argument("--db", default=None, help="SQLite database path")
    args = parser.parse_args(argv)
    service = build_service(args.db)
    print(
        f"trustmed-mcp {__version__}: {service.store.count('asset')} assets, "
        f"{service.store.event_count()} audit events",
        file=sys.stderr,
    )
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        response = handle_line(line, service)
        if response is not None:
            print(json.dumps(response, ensure_ascii=False), flush=True)
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
