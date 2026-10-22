
import jsonschema

from trustmed_fabric.mcp_server import TOOLS


def test_mcp_tool_schemas_are_valid(service) -> None:
    for tool in TOOLS:
        jsonschema.Draft202012Validator.check_schema(tool["inputSchema"])
        assert tool["annotations"]["readOnlyHint"] is True


def test_openapi_contains_core_paths(client) -> None:
    response = client.get("/openapi.json")
    assert response.status_code == 200
    paths = response.json()["paths"]
    assert "/api/v1/ask" in paths
    assert "/api/v1/audit/verify" in paths
    assert "/mcp" in paths


def test_api_extra_fields_rejected(client) -> None:
    response = client.post("/api/v1/policy/evaluate", json={"asset_id": "ONC-HCP-DA-001", "market": "US", "audience": "HCP", "channel": "WEB", "extra": True})
    assert response.status_code == 422
