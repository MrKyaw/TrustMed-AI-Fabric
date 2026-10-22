# About TrustMed AI Fabric

TrustMed AI Fabric is a portfolio-grade reference implementation of a governed
content supply chain for regulated life-sciences organisations. It is built to
demonstrate engineering judgement in AI governance, auditability, content
operations and measurement, not to be a production SaaS product.

## What it demonstrates

- A complete content lifecycle from claim substantiation to publication and
  measurement.
- A policy engine that blocks unsafe or non-compliant content before it is
  retrieved or published.
- A governed assistant that refuses unsafe requests and cites approved sources.
- A tamper-evident audit ledger that makes every state change provable.
- A fail-closed evaluation gate with committed artifacts.
- A polished operator console and multiple machine interfaces.

## Intended audience

- Hiring managers and reviewers looking for evidence of system design.
- Engineers interested in governed RAG, policy engines and audit ledgers.
- Academics studying traceability and evaluation of AI-assisted content.
- Contributors who want a compact, dependency-light reference platform.

## Key design principles

1. **Controls before generation.** Retrieval is filtered to approved content
   before any term is scored.
2. **Evidence over fluency.** Answers are extractive and cited.
3. **Fail closed.** Missing evidence, expired approvals and unsafe framing
   block the answer.
4. **Reproducibility.** Fixed anchors make ledger hashes and evaluation
   results deterministic.
5. **Auditability.** Every state change is hash-chained and exportable.
6. **Synthetic by construction.** No real patient or promotional data is used.

## Repository topics

`ai-governance`, `content-supply-chain`, `life-sciences`, `mcp`,
`traceability`, `rag`, `evaluation`, `fastapi`, `audit-ledger`.

## Why the project is useful

The repository is intentionally small enough to read in an afternoon, but
complete enough to show how governance, retrieval, measurement and audit fit
together. It can be used as a template for internal prototypes, a teaching
example, or a starting point for a production platform.
