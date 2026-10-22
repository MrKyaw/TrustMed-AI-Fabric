from trustmed_fabric.mcp_server import dispatch


def test_mcp_initialize_and_tools(service) -> None:
    init = dispatch({"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}}, service)
    assert init["result"]["protocolVersion"] == "2025-06-18"
    tools = dispatch({"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}}, service)
    assert len(tools["result"]["tools"]) == 7


def test_mcp_call_tool(service) -> None:
    response = dispatch(
        {
            "jsonrpc": "2.0",
            "id": 3,
            "method": "tools/call",
            "params": {"name": "check_claim", "arguments": {"claim_id": "CLM-001", "market": "US"}},
        },
        service,
    )
    assert response["result"]["isError"] is False
    assert "CLM-001" in response["result"]["content"][0]["text"]


def test_mcp_unknown_method(service) -> None:
    response = dispatch({"jsonrpc": "2.0", "id": 4, "method": "nope", "params": {}}, service)
    assert response["error"]["code"] == -32601


def test_mcp_notification(service) -> None:
    assert dispatch({"jsonrpc": "2.0", "method": "notifications/initialized", "params": {}}, service) is None
