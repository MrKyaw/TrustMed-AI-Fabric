# Architecture

TrustMed AI Fabric is a single-process reference platform. All entry points
(API, MCP and CLI) share one `FabricService`, so policy, retrieval and audit
behaviour cannot drift between interfaces.

## Runtime flow

1. **Seeding** loads synthetic content, experiences, publications, metrics and
   insights into SQLite and writes a deterministic audit trail.
2. **Policy evaluation** combines approval, market fit, taxonomy, claim,
   fair-balance, consent, privacy and platform checks.
3. **Retrieval** builds a BM25 index over approved sections only. Draft and
   expired assets are excluded before scoring.
4. **Assistant** screens input, retrieves approved passages, composes an
   extractive cited answer, verifies output guardrails and records the trace.
5. **Evaluation** runs 30 golden cases and applies a fail-closed quality gate.
6. **Audit** stores every event in a SHA-256 hash chain that can be verified
   and exported.

## Storage model

- `entities` stores versioned JSON documents by type and id.
- `ledger` stores append-only audit events with `prev_hash` and `hash`.
- `edges` stores provenance relationships created with ledger events.
- `ai_traces` stores question, answer, citations and guardrail results.
- `idempotency` stores publication replay keys.

## Extending the platform

- Replace SQLite with PostgreSQL by implementing the same store contract.
- Add a hosted model behind the assistant composition step; output checks remain
  mandatory.
- Add new policy controls as `PolicyFinding` producers in `PolicyEngine`.
- Add golden cases to `src/trustmed_fabric/data/evals.json`.
