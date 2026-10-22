"""FastAPI application: REST, OpenAPI, dashboard and an HTTP MCP endpoint."""

from __future__ import annotations

import time
from pathlib import Path
from typing import Any, cast

from fastapi import APIRouter, Body, Depends, FastAPI, Header, HTTPException, Query, Request
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles

from trustmed_fabric import __version__
from trustmed_fabric.api_schemas import ClaimCheckRequest, EvaluateRequest, PublishRequest
from trustmed_fabric.errors import FabricError
from trustmed_fabric.mcp_server import dispatch as mcp_dispatch
from trustmed_fabric.models import (
    AskRequest,
    AssetStatus,
    Audience,
    Market,
)
from trustmed_fabric.observability import MetricsRegistry
from trustmed_fabric.service import FabricService
from trustmed_fabric.settings import Settings
from trustmed_fabric.store import Store
from trustmed_fabric.timeutil import new_id, utcnow

WEB_DIR = Path(__file__).parent / "web"


def create_app(
    service: FabricService | None = None,
    *,
    settings: Settings | None = None,
    api_key: str | None = None,
    db_path: str | None = None,
) -> FastAPI:
    active_settings = settings or Settings.from_env()
    if service is None:
        store = Store(db_path or active_settings.db_path)
        service = FabricService(
            store,
            auto_seed=active_settings.auto_seed,
            report_path=active_settings.report_path,
            now=utcnow(),
        )
    app = FastAPI(
        title="TrustMed AI Fabric",
        version=__version__,
        description=(
            "Governed, traceable AI fabric for regulated content, experiences and measurement. "
            "All data in the reference deployment is synthetic."
        ),
        contact={"name": "MrKyaw", "url": "https://github.com/MrKyaw/TrustMed-AI-Fabric"},
        license_info={"name": "MIT", "url": "https://opensource.org/licenses/MIT"},
    )
    app.state.service = service
    app.state.metrics = MetricsRegistry()
    app.state.api_key = active_settings.api_key if api_key is None else api_key
    app.state.started_at = utcnow()

    @app.middleware("http")
    async def observability(request: Request, call_next: Any) -> Response:
        started = time.perf_counter()
        trace_id = request.headers.get("x-trace-id") or new_id("req")
        try:
            response = await call_next(request)
        except Exception:
            latency = (time.perf_counter() - started) * 1000
            app.state.metrics.record_request(request.url.path, 500, latency)
            raise
        latency = (time.perf_counter() - started) * 1000
        app.state.metrics.record_request(request.url.path, response.status_code, latency)
        response.headers["X-Trace-ID"] = trace_id
        response.headers["X-Response-Time-ms"] = f"{latency:.2f}"
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "same-origin"
        return cast(Response, response)

    @app.exception_handler(FabricError)
    async def fabric_error_handler(_: Request, exc: FabricError) -> JSONResponse:
        return JSONResponse(status_code=exc.status_code, content={"error": exc.to_dict()})

    @app.exception_handler(RequestValidationError)
    async def validation_error_handler(_: Request, exc: RequestValidationError) -> JSONResponse:
        return JSONResponse(
            status_code=422,
            content={
                "error": {
                    "code": "VALIDATION_ERROR",
                    "message": "request validation failed",
                    "details": jsonable_encoder(exc.errors()),
                }
            },
        )

    @app.exception_handler(HTTPException)
    async def http_error_handler(_: Request, exc: HTTPException) -> JSONResponse:
        message = exc.detail if isinstance(exc.detail, str) else "request failed"
        code = "UNAUTHORIZED" if exc.status_code == 401 else "HTTP_ERROR"
        return JSONResponse(
            status_code=exc.status_code,
            content={"error": {"code": code, "message": message, "details": {}}},
            headers=exc.headers,
        )

    def require_api_key(request: Request) -> None:
        expected = request.app.state.api_key
        if not expected:
            return
        if request.headers.get("x-api-key") != expected:
            raise HTTPException(status_code=401, detail="missing or invalid API key")

    api = APIRouter(prefix="/api/v1", dependencies=[Depends(require_api_key)])

    @app.get("/healthz", tags=["operations"])
    def healthz() -> dict[str, Any]:
        return {
            "status": "ok",
            "version": __version__,
            "dataset": "synthetic",
            "time": utcnow().isoformat(),
        }

    @app.get("/readyz", tags=["operations"])
    def readyz() -> Response:
        verification = service.audit_verify()
        body = {
            "status": "ready" if verification["valid"] else "degraded",
            "ledger": verification,
            "counts": service.store.table_counts(),
        }
        return JSONResponse(body, status_code=200 if verification["valid"] else 503)

    @api.get("/overview", tags=["analytics"])
    def overview(market: Market | None = None) -> dict[str, Any]:
        result = service.overview()
        if market is not None:
            result["funnel"] = service.funnel(market=market)
        return result

    @api.get("/funnel", tags=["analytics"])
    def funnel(market: Market | None = None) -> dict[str, Any]:
        return service.funnel(market=market)

    @api.get("/assets", tags=["content"])
    def assets(
        market: Market | None = None,
        audience: Audience | None = None,
        asset_status: AssetStatus | None = Query(default=None, alias="status"),
        q: str | None = Query(default=None, max_length=120),
    ) -> dict[str, Any]:
        items = service.list_assets(
            market=market, audience=audience, status=asset_status, q=q
        )
        return {"items": items, "count": len(items)}

    @api.get("/assets/{asset_id}", tags=["content"])
    def asset_detail(asset_id: str) -> dict[str, Any]:
        return service.asset_detail(asset_id)

    @api.get("/assets/{asset_id}/lineage", tags=["lineage"])
    def asset_lineage(asset_id: str) -> dict[str, Any]:
        return service.lineage(asset_id)

    @api.get("/assets/{asset_id}/impact", tags=["lineage"])
    def asset_impact(asset_id: str) -> dict[str, Any]:
        return service.lineage(asset_id)

    @api.get("/claims", tags=["governance"])
    def claims() -> dict[str, Any]:
        items = service.list_claims()
        return {"items": items, "count": len(items)}

    @api.get("/claims/{claim_id}", tags=["governance"])
    def claim_detail(claim_id: str, market: Market = Market.US) -> dict[str, Any]:
        return service.assess_claim(claim_id, market).model_dump(mode="json")

    @api.post("/claims/check", tags=["governance"])
    def claim_check(payload: ClaimCheckRequest) -> dict[str, Any]:
        return service.assess_claim(payload.claim_id, payload.market).model_dump(mode="json")

    @api.get("/experiences", tags=["content"])
    def experiences() -> dict[str, Any]:
        items = service.list_experiences()
        return {"items": items, "count": len(items)}

    @api.get("/publications", tags=["content"])
    def publications() -> dict[str, Any]:
        items = service.list_publications()
        return {"items": items, "count": len(items)}

    @api.post("/publications", status_code=201, tags=["content"])
    def publish(
        payload: PublishRequest,
        idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
    ) -> JSONResponse:
        result = service.publish(
            asset_id=payload.asset_id,
            experience_id=payload.experience_id,
            destination=payload.destination,
            idempotency_key=idempotency_key,
        )
        return JSONResponse(
            result,
            status_code=201,
            headers={"Idempotent-Replay": str(result["idempotent_replay"]).lower()},
        )

    @api.get("/policy/catalog", tags=["governance"])
    def policy_catalog() -> dict[str, Any]:
        policies = service.policy_catalog()
        return {"items": policies, "count": len(policies)}

    @api.post("/policy/evaluate", tags=["governance"])
    def policy_evaluate(payload: EvaluateRequest) -> dict[str, Any]:
        decision = service.evaluate(
            payload.asset_id,
            payload.market,
            payload.audience,
            payload.channel,
            experience_id=payload.experience_id,
            for_publication=payload.for_publication,
        )
        return decision.model_dump(mode="json")

    @api.get("/taxonomy", tags=["governance"])
    def taxonomy() -> dict[str, Any]:
        items = service.taxonomy_list()
        return {
            "version": service.taxonomy.version,
            "items": items,
            "count": len(items),
        }

    @api.get("/insights", tags=["analytics"])
    def insights() -> dict[str, Any]:
        items = service.insights()
        return {"items": items, "count": len(items)}

    @api.post("/ask", tags=["assistant"])
    def ask(payload: AskRequest) -> dict[str, Any]:
        response = service.ask(payload)
        app.state.metrics.record_answer(response.refused)
        return response.model_dump(mode="json")

    @api.get("/traces/{trace_id}", tags=["assistant"])
    def trace(trace_id: str) -> dict[str, Any]:
        return service.get_trace(trace_id)

    @api.get("/evals/latest", tags=["evaluation"])
    def evals_latest() -> dict[str, Any]:
        report = service.eval_report()
        if report is None:
            raise HTTPException(status_code=503, detail="evaluation report is not available")
        return report.model_dump(mode="json")

    @api.post("/evals/run", tags=["evaluation"])
    def evals_run() -> dict[str, Any]:
        report, json_path, md_path = service.refresh_eval_report()
        return {
            "report": report.model_dump(mode="json"),
            "artifacts": {"json": str(json_path), "markdown": str(md_path)},
        }

    @api.get("/audit/events", tags=["audit"])
    def audit_events(
        limit: int = Query(default=50, ge=1, le=500),
        after_sequence: int = Query(default=0, ge=0),
        subject_id: str | None = None,
    ) -> dict[str, Any]:
        events = service.audit_events(
            limit=limit, after_sequence=after_sequence, subject_id=subject_id
        )
        return {"items": events, "count": len(events), "ledger_events": service.store.event_count()}

    @api.get("/audit/verify", tags=["audit"])
    def audit_verify() -> dict[str, Any]:
        return service.audit_verify()

    @api.get("/audit/export", tags=["audit"])
    def audit_export() -> Response:
        lines = service.audit_export_lines()
        return Response(
            content="\n".join(lines) + "\n",
            media_type="application/x-ndjson",
            headers={
                "Content-Disposition": 'attachment; filename="trustmed-audit-ledger.ndjson"'
            },
        )

    @api.get("/ops/metrics", tags=["operations"])
    def ops_metrics() -> dict[str, Any]:
        snapshot = cast(dict[str, Any], app.state.metrics.snapshot())
        snapshot["service"] = {
            "version": __version__,
            "assets": service.store.count("asset"),
            "ledger_events": service.store.event_count(),
            "taxonomy_version": service.taxonomy.version,
            "anchor": service.anchor.isoformat(),
        }
        return snapshot

    app.include_router(api)

    @app.post("/mcp", tags=["mcp"], dependencies=[Depends(require_api_key)])
    def mcp_endpoint(payload: dict[str, Any] = Body(...)) -> Response:
        response = mcp_dispatch(payload, service)
        if response is None:
            return Response(status_code=204)
        return JSONResponse(response)

    if WEB_DIR.exists():
        app.mount("/static", StaticFiles(directory=WEB_DIR), name="static")

        @app.get("/", include_in_schema=False)
        def dashboard() -> FileResponse:
            return FileResponse(WEB_DIR / "index.html")

        @app.get("/favicon.svg", include_in_schema=False)
        def favicon() -> FileResponse:
            return FileResponse(WEB_DIR / "favicon.svg")

    return app


def get_app() -> FastAPI:
    """Factory target for ``uvicorn trustmed_fabric.api:get_app --factory``."""

    return create_app()
