# TrustMed AI Fabric

[![CI](https://github.com/MrKyaw/TrustMed-AI-Fabric/actions/workflows/ci.yml/badge.svg)](https://github.com/MrKyaw/TrustMed-AI-Fabric/actions/workflows/ci.yml)
[![Coverage](https://img.shields.io/badge/coverage-90%25-brightgreen)](reports/coverage.txt)
[![Python](https://img.shields.io/badge/python-3.11%2B-blue)](pyproject.toml)
[![License: MIT](https://img.shields.io/badge/license-MIT-green)](LICENSE)

A governed, traceable AI fabric for regulated life-sciences content, digital
experiences and measurement. This repository is an original, synthetic reference
implementation: every brand, study, evidence record and measurement row is
fictional, and no real patient data is present.

TrustMed AI Fabric demonstrates how a content supply chain can be made
auditable end to end: approved claims are tied to evidence, assets are approved
with expiry, publications are pinned to approved versions, measurement is linked
back to the content that produced it, and an AI assistant can answer only from
currently approved material with section-level citations and a hash-chained audit
trail.

## Why this project

Regulated marketing and medical-education teams need to move quickly without
losing control of what is said, where it is said and how it performs. TrustMed
AI Fabric models that problem as a single control plane:

- **Content governance** – approval status, version pinning, expiry, market,
  audience and channel fit.
- **Claim substantiation** – every claim must be approved, market-valid and
  backed by in-date evidence.
- **Traceability** – assets, claims, evidence, publications, experiences,
  metrics and insights are connected in a graph that is reconstructable from
  the audit ledger.
- **Governed AI** – retrieval is filtered to approved content before scoring;
  answers are extractive, cited and checked for grounding, fair balance and
  prohibited language.
- **Measurement and learning** – impressions, engagements and qualified actions
  roll up to documented insights with confidence scores.
- **Tamper-evident audit** – every state change is an append-only, SHA-256
  hash-chained ledger event.

## Quick start

```bash
git clone https://github.com/MrKyaw/TrustMed-AI-Fabric.git
cd TrustMed-AI-Fabric
python3 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
PYTHONPATH=src python3 -m trustmed_fabric.cli seed
PYTHONPATH=src python3 -m uvicorn trustmed_fabric.api:get_app --factory --port 8080
```

Open the operator console at <http://127.0.0.1:8080>.

### Docker

```bash
docker compose up --build
```

The container exposes the API and console on port 8080 and persists the SQLite
database and reports in named volumes.

## Core capabilities

| Area | Implementation |
| --- | --- |
| Domain model | Pydantic v2 models with strict validation and `extra="forbid"` |
| Storage | SQLite with WAL, versioned entities and an append-only ledger |
| Audit | SHA-256 hash chain, genesis hash, sequence checks, NDJSON export |
| Policy | 12 composable controls: approval, market fit, taxonomy, claims, fair balance, consent, privacy, platform surface |
| Retrieval | Deterministic BM25 over approved sections only, with taxonomy expansion |
| Assistant | Input/output guardrails, extractive cited answers, safe refusals |
| Evaluation | 30 golden cases, fail-closed quality gate, Markdown and JSON reports |
| Interfaces | FastAPI REST + OpenAPI, MCP server (stdio and HTTP), CLI, browser console |
| Observability | Request metrics, latency percentiles, trace IDs, readiness checks |

## Architecture

```text
src/trustmed_fabric/
├── api.py              FastAPI app, routes, dashboard and HTTP MCP endpoint
├── service.py          Shared orchestration used by API, MCP and CLI
├── assistant.py        Governed assistant and audit finishing
├── retrieval.py        Approved-content BM25 index
├── policies.py         Policy catalog and engine
├── claims.py           Claim substantiation and evidence validity
├── lineage.py          Provenance graph and governance gap detection
├── store.py            SQLite persistence and hash-chained ledger
├── seed.py             Deterministic synthetic dataset
├── evals.py            Golden-set evaluation harness
├── mcp_server.py       Model Context Protocol server
├── cli.py              Operator CLI
└── web/                Static operator console
```

See [docs/architecture.md](docs/architecture.md) for the full design.

## Synthetic data

- Brands: **Oncravia** (oncology) and **Aerivant** (respiratory).
- Markets: US, CA, UK, DE, FR. Approved content exists only for US, CA and UK,
  which lets the assistant demonstrate correct refusals for DE, FR and caregiver
  audiences.
- All studies, citations, metrics and insights are synthetic and labelled as
  such. No real patient data is used.

## Evaluation and test results

The golden evaluation suite contains 30 cases and currently reports:

| Metric | Result | Threshold |
| --- | ---: | ---: |
| Case pass rate | 1.000 | 1.000 |
| Citation validity | 1.000 | 1.000 |
| Refusal accuracy | 1.000 | 1.000 |
| Retrieval recall@3 | 1.000 | 0.900 |
| Groundedness | 1.000 | 0.900 |
| p95 latency | 3.231 ms | 5000 ms |

The test suite contains 96 tests and reports 90% branch-aware coverage.
Committed artifacts:

- [reports/eval-report.json](reports/eval-report.json)
- [reports/eval-report.md](reports/eval-report.md)
- [reports/test-results.txt](reports/test-results.txt)
- [reports/coverage.txt](reports/coverage.txt)

## MCP tools

The MCP server exposes seven read-only, governed tools:

1. `search_approved_content`
2. `get_content_lineage`
3. `evaluate_content_policy`
4. `check_claim`
5. `get_campaign_insights`
6. `ask_governed_assistant`
7. `get_audit_manifest`

Run it over stdio:

```bash
PYTHONPATH=src python3 -m trustmed_fabric.mcp_server
```

Or use the HTTP endpoint at `/mcp` when the API is running.

## CLI examples

```bash
# Seed or reset the synthetic dataset
trustmed seed --reset

# Ask a governed question
trustmed ask "What progression-free survival result did HORIZON-3 show for Oncravia?" --market US --audience HCP

# Evaluate an asset
trustmed evaluate ONC-HCP-DA-001 --market US --audience HCP --channel WEB

# Trace lineage
trustmed trace ONC-HCP-DA-001

# Run the golden evaluation
trustmed eval

# Verify the audit chain
trustmed audit verify
```

## API highlights

- `GET /healthz`, `GET /readyz`
- `GET /api/v1/overview`, `GET /api/v1/funnel`
- `GET /api/v1/assets`, `GET /api/v1/assets/{id}`, `GET /api/v1/assets/{id}/lineage`
- `GET /api/v1/claims`, `POST /api/v1/claims/check`
- `GET /api/v1/experiences`, `GET /api/v1/publications`, `POST /api/v1/publications`
- `GET /api/v1/policy/catalog`, `POST /api/v1/policy/evaluate`
- `GET /api/v1/taxonomy`, `GET /api/v1/insights`
- `POST /api/v1/ask`, `GET /api/v1/traces/{trace_id}`
- `GET /api/v1/evals/latest`, `POST /api/v1/evals/run`
- `GET /api/v1/audit/events`, `GET /api/v1/audit/verify`, `GET /api/v1/audit/export`

Interactive OpenAPI documentation is available at `/docs`.

## Development

```bash
make test        # pytest with coverage gate
make lint        # ruff
make typecheck   # mypy
make eval        # golden evaluation suite
```

See [CONTRIBUTING.md](CONTRIBUTING.md), [SECURITY.md](SECURITY.md) and
[docs/testing.md](docs/testing.md).

## Project status

Version 1.0.0. The reference implementation is complete and all 96 tests pass.
Future work is tracked in [docs/roadmap.md](docs/roadmap.md).

## Screenshots

### Command centre

![Command centre](docs/assets/dashboard-overview.png)

### Content lineage

![Content lineage](docs/assets/dashboard-lineage.png)

### Governed assistant

![Governed assistant](docs/assets/dashboard-assistant-answer.png)

### Governance controls

![Governance controls](docs/assets/dashboard-governance.png)

### Evaluation fabric

![Evaluation fabric](docs/assets/dashboard-evaluations.png)

### Audit ledger

![Audit ledger](docs/assets/dashboard-audit.png)

## Design notes

- The assistant is deliberately extractive. Every substantive sentence is taken
  from an approved section and carries a citation, which makes grounding
  measurable and makes unsupported generation structurally impossible in the
  offline reference mode.
- Retrieval is filtered before scoring. Draft, expired, out-of-market and
  audience-mismatched text never reaches the prompt.
- The audit ledger is append-only and hash-chained. Verification recomputes
  every hash and checks sequence continuity.
- The evaluation gate is fail-closed. A single failing case fails the build.

## Extended documentation

- [Architecture](docs/architecture.md)
- [AI governance](docs/ai-governance.md)
- [Lineage and traceability](docs/lineage.md)
- [Data contracts](docs/data-contracts.md)
- [Evaluation](docs/evals.md)
- [MCP tools](docs/mcp.md)
- [Testing](docs/testing.md)
- [Runbook](docs/runbook.md)
- [Threat model](docs/threat-model.md)
- [Roadmap](docs/roadmap.md)
- [About](docs/about.md)

## License

MIT. See [LICENSE](LICENSE).

## Citation

If you use this project in research or evaluation work, please cite it using
[CITATION.cff](CITATION.cff).

---

⭐ Star this repo if you find it useful!

[Report Bug](https://github.com/MrKyaw/TrustMed-AI-Fabric/issues) · [Request Feature](https://github.com/MrKyaw/TrustMed-AI-Fabric/issues) · [Ask Question](https://github.com/MrKyaw/TrustMed-AI-Fabric/discussions)
