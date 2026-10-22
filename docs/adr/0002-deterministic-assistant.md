# ADR 0002: Deterministic extractive assistant

## Status

Accepted.

## Context

A hosted LLM would make the demo non-reproducible and would hide the
governance path.

## Decision

Compose answers extractively from approved passages and require output
guardrails.

## Consequences

- Grounding is measurable.
- The same contract can later host a model.
- Answers are less fluent than a generative model.
