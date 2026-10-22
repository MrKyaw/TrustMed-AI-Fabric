def test_health_and_ready(client) -> None:
    health = client.get("/healthz")
    assert health.status_code == 200
    assert health.json()["status"] == "ok"
    ready = client.get("/readyz")
    assert ready.status_code == 200
    assert ready.json()["status"] == "ready"


def test_overview_and_assets(client) -> None:
    overview = client.get("/api/v1/overview")
    assert overview.status_code == 200
    assert overview.json()["kpis"]["approved_assets"] >= 1
    assets = client.get("/api/v1/assets", params={"market": "US", "status": "APPROVED"})
    assert assets.status_code == 200
    assert assets.json()["count"] >= 1
    detail = client.get("/api/v1/assets/ONC-HCP-DA-001")
    assert detail.status_code == 200
    assert detail.json()["asset"]["id"] == "ONC-HCP-DA-001"


def test_claims_insights_taxonomy_audit(client) -> None:
    claims = client.get("/api/v1/claims")
    assert claims.status_code == 200
    assert claims.json()["count"] >= 1
    insights = client.get("/api/v1/insights")
    assert insights.status_code == 200
    taxonomy = client.get("/api/v1/taxonomy")
    assert taxonomy.status_code == 200
    audit = client.get("/api/v1/audit/verify")
    assert audit.status_code == 200
    assert audit.json()["valid"] is True
    events = client.get("/api/v1/audit/events", params={"limit": 5})
    assert events.status_code == 200
    assert len(events.json()["items"]) <= 5


def test_ask_endpoint(client) -> None:
    response = client.post(
        "/api/v1/ask",
        json={"question": "What progression-free survival result did HORIZON-3 show for Oncravia?", "market": "US", "audience": "HCP"},
    )
    assert response.status_code == 200
    assert response.json()["refused"] is False
    assert response.json()["citations"]


def test_auth_required(authed_client) -> None:
    assert authed_client.get("/api/v1/overview").status_code == 401
    assert authed_client.get("/api/v1/overview", headers={"X-API-Key": "secret-key"}).status_code == 200


def test_publish_idempotency(client) -> None:
    response = client.post(
        "/api/v1/publications",
        headers={"Idempotency-Key": "publish-test"},
        json={
            "asset_id": "ONC-HCP-DA-001",
            "experience_id": "EXP-WEB-US-ONC-HCP",
            "destination": "https://demo.trustmed.example/test",
        },
    )
    assert response.status_code == 201
    replay = client.post(
        "/api/v1/publications",
        headers={"Idempotency-Key": "publish-test"},
        json={
            "asset_id": "ONC-HCP-DA-001",
            "experience_id": "EXP-WEB-US-ONC-HCP",
            "destination": "https://demo.trustmed.example/test",
        },
    )
    assert replay.status_code == 201
    assert replay.json()["idempotent_replay"] is True
    assert replay.headers["Idempotent-Replay"] == "true"


def test_mcp_http_endpoint(client) -> None:
    response = client.post("/mcp", json={"jsonrpc": "2.0", "id": 1, "method": "tools/list", "params": {}})
    assert response.status_code == 200
    tools = response.json()["result"]["tools"]
    assert len(tools) == 7
    assert tools[0]["name"] == "search_approved_content"


def test_dashboard_and_static(client) -> None:
    dashboard = client.get("/")
    assert dashboard.status_code == 200
    assert "TrustMed" in dashboard.text
    static = client.get("/static/styles.css")
    assert static.status_code == 200
    favicon = client.get("/favicon.svg")
    assert favicon.status_code == 200
