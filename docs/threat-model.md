# Threat model

## In scope

- Prompt injection through user questions.
- Personal data in questions or content.
- Prohibited absolute or curative claims.
- Unapproved or expired content reaching answers.
- Tampering with the audit ledger.
- Unauthorised API access when an API key is configured.

## Controls

- Input and output guardrails.
- Approval, market, channel and audience checks.
- Hash-chained ledger with verification.
- API key middleware.
- Synthetic data only.

## Out of scope

- Production identity and access management.
- Multi-tenant isolation.
- Network-level hardening.
- Real pharmacovigilance workflows.
