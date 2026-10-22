# About TrustMed AI Fabric

TrustMed AI Fabric is a portfolio-grade reference implementation of a governed
content supply chain for regulated life-sciences organisations. It is built to
demonstrate engineering judgement in AI governance, auditability, content
operations and measurement, not to be a production SaaS product.

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
