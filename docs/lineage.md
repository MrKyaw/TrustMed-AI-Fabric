# Lineage and traceability

Lineage is stored as namespaced nodes (`asset:`, `claim:`, `evidence:`) and
edges created only when a ledger event is appended. This makes the graph
reconstructable from the audit trail.

## Supported traversals

- Asset to claims, evidence, publications, experiences, metrics and insights.
- Entity-level subgraphs for any node type.
- Cross-cutting governance gap detection.

## Governance gaps

The platform reports expired approvals linked to live publications, live
publications without measurement, measured publications without insights and
approved assets that have never been published.
