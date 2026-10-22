# AI governance

The governed assistant is designed so that unsafe generation is structurally
difficult.

## Input controls

- Prompt-injection detection.
- Personal-data detection and redaction.
- Prohibited absolute or curative framing detection.
- Clinical-advice refusal.
- Unapproved-content reference detection.

## Retrieval controls

- Only approved, in-date, market-, audience- and channel-matching assets enter
  the corpus.
- BM25 scoring happens after eligibility filtering.
- Draft and expired text never reaches the prompt.

## Output controls

- Extractive composition from approved passages.
- Section-level citations with content hashes.
- Grounding score of at least 0.85.
- Fair-balance safety context.
- Prohibited language check.
- Length bound.

## Audit

Every answer, including refusals, is recorded in the hash-chained ledger with
redacted question text, checks, citations and latency.
