# Evaluation

The golden suite contains 30 cases covering:

- efficacy and safety retrieval
- patient support content
- market-specific evidence
- out-of-market refusals
- unapproved-content refusals
- prompt injection
- personal data
- prohibited framing
- clinical advice

## Quality gate

The gate is fail-closed. All of the following must pass:

- case pass rate >= 1.0
- citation validity >= 1.0
- refusal accuracy >= 1.0
- retrieval recall@3 >= 0.9
- groundedness >= 0.9

Reports are written to `reports/eval-report.json` and
`reports/eval-report.md`.
