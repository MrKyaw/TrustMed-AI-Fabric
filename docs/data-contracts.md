# Data contracts

All domain objects are Pydantic v2 models with `extra="forbid"`. This makes
the schema part of the control surface: unknown fields are rejected at every
boundary.

## Core entities

- `Asset` – versioned content with sections, tags, claims and approval.
- `Claim` – approved wording with evidence links and market authorisation.
- `Evidence` – source record with market and date validity.
- `Experience` – digital surface with consent and tracking metadata.
- `Publication` – approved asset version delivered through an experience.
- `Metric` – impressions, engagements and qualified actions.
- `Insight` – documented learning with confidence.
- `LedgerEvent` – hash-chained audit record.

## Invariants

- Approved assets require an approval record.
- Section claim ids must be a subset of asset claim ids.
- Evidence must expire after it becomes effective.
- Metric engagements cannot exceed impressions.
- Publication content hashes must match the approved asset version.
- All timestamps are timezone-aware UTC.
