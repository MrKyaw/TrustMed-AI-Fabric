# ADR 0001: SQLite and a hash-chained ledger

## Status

Accepted.

## Context

The reference platform must run with zero external services while still
demonstrating production-shaped auditability.

## Decision

Use SQLite for storage and an append-only SHA-256 hash-chained ledger for audit
events.

## Consequences

- Local development is trivial.
- The store contract can be replaced with PostgreSQL in production.
- The ledger is tamper-evident but not distributed; production should add
  external anchoring.
