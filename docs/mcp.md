# Model Context Protocol

TrustMed AI Fabric exposes seven read-only tools over stdio and HTTP. There is
deliberately no publish or approve tool: agents may inspect, evaluate and
retrieve, but distribution requires a human workflow.

## Running

```bash
PYTHONPATH=src python3 -m trustmed_fabric.mcp_server
```

HTTP endpoint: `POST /mcp` with JSON-RPC 2.0.

## Tool list

- `search_approved_content`
- `get_content_lineage`
- `evaluate_content_policy`
- `check_claim`
- `get_campaign_insights`
- `ask_governed_assistant`
- `get_audit_manifest`
