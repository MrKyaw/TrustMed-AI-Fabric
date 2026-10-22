"""The governed assistant: retrieval, composition, guardrails and audit.

Composition is deliberately extractive. Every substantive sentence is quoted
from an approved section and carries a citation, which makes grounding
measurable and makes unsupported generation structurally impossible in the
offline reference mode. A hosted model can be added behind the same contract,
but it cannot bypass the output checks.
"""

from __future__ import annotations

import re
import time
from datetime import datetime
from typing import Any

from trustmed_fabric.claims import ClaimRegistry
from trustmed_fabric.guardrails import screen_input, verify_answer
from trustmed_fabric.language import redact_pii
from trustmed_fabric.models import (
    AskRequest,
    AskResponse,
    Asset,
    Audience,
    Citation,
    Experience,
    ExperienceStatus,
    GuardrailCheck,
    Market,
    PolicyDecision,
    RetrievedPassage,
)
from trustmed_fabric.policies import PolicyEngine
from trustmed_fabric.retrieval import (
    GENERIC_TERMS,
    SENTENCE_RE,
    RetrievalIndex,
    SearchFilters,
    tokenize,
)
from trustmed_fabric.store import Store
from trustmed_fabric.taxonomy import Taxonomy
from trustmed_fabric.timeutil import ensure_utc, new_id, utcnow

MODEL_NAME = "deterministic-extractive-v1"

REFUSAL_MESSAGES: dict[str, str] = {
    "PROMPT_INJECTION": (
        "I can't follow instructions that try to change my role or expose internal "
        "configuration. I can help you find current approved content."
    ),
    "PII_IN_INPUT": (
        "I can't process personal data such as email addresses, phone numbers or record "
        "numbers. Remove the personal data and ask again; the request will not be retained "
        "in the audit record with those values."
    ),
    "PROHIBITED_FRAMING": (
        "Approved content does not support absolute, guaranteed or curative framing. I can "
        "share the approved evidence and its precise wording instead."
    ),
    "CLINICAL_ADVICE": (
        "I can't provide prescribing, diagnosis or treatment advice. I can retrieve approved "
        "content for a qualified healthcare professional to review."
    ),
    "UNAPPROVED_REFERENCE": (
        "I can't use draft, unapproved or withdrawn material. I can search current approved "
        "content for the same topic instead."
    ),
    "NO_APPROVED_CONTENT": (
        "I can't answer from approved content for this request. No current approval matched "
        "the market, audience and topic. Try another market or broaden the question."
    ),
    "OUTPUT_GUARDRAIL": (
        "I blocked the drafted answer because it did not meet the citation, grounding, "
        "fair-balance or language controls. No unverified text was returned."
    ),
}


class GovernedAssistant:
    def __init__(
        self,
        store: Store,
        taxonomy: Taxonomy,
        index: RetrievalIndex,
        claims: ClaimRegistry,
        policies: PolicyEngine,
    ) -> None:
        self.store = store
        self.taxonomy = taxonomy
        self.index = index
        self.claims = claims
        self.policies = policies

    def ask(self, request: AskRequest, *, now: datetime | None = None) -> AskResponse:
        started = time.perf_counter()
        trace_id = new_id("trc")
        as_of = ensure_utc(request.as_of or now or utcnow())
        screen = screen_input(request.question)
        if screen.reason is not None:
            return self._finish(
                request=request,
                trace_id=trace_id,
                started=started,
                answer=REFUSAL_MESSAGES[screen.reason],
                refused=True,
                refusal_reason=screen.reason,
                citations=[],
                decision=None,
                checks=screen.checks,
                context_pack="",
                retrieval_meta={"reason": screen.reason},
                as_of=as_of,
            )

        filters = SearchFilters(
            market=request.market,
            audience=request.audience,
            channel=request.channel,
            as_of=as_of,
        )
        result = self.index.search(request.question, filters, limit=request.limit)
        meta: dict[str, Any] = {
            "eligible_assets": result.eligible_assets,
            "matched_assets": result.matched_assets,
            "index_version": result.index_version,
            "query_terms": sorted(set(result.query_terms)),
        }
        coverage_check = GuardrailCheck(
            id="CONTEXT-COVERAGE",
            passed=bool(result.passages),
            message=(
                f"{len(result.passages)} passage(s) retrieved from approved content"
                if result.passages
                else "No approved content matched the market, audience and question"
            ),
        )
        checks = [*screen.checks, coverage_check]
        if not result.passages:
            return self._finish(
                request=request,
                trace_id=trace_id,
                started=started,
                answer=REFUSAL_MESSAGES["NO_APPROVED_CONTENT"],
                refused=True,
                refusal_reason="NO_APPROVED_CONTENT",
                citations=[],
                decision=None,
                checks=checks,
                context_pack="",
                retrieval_meta=meta,
                as_of=as_of,
            )

        covered, missing = self._topic_covered(request.question, result.passages)
        if not covered:
            checks.append(
                GuardrailCheck(
                    id="CONTEXT-TOPIC",
                    passed=False,
                    message="The question's key topic terms are absent from approved content",
                )
            )
            meta["missing_terms"] = sorted(missing)
            return self._finish(
                request=request,
                trace_id=trace_id,
                started=started,
                answer=REFUSAL_MESSAGES["NO_APPROVED_CONTENT"],
                refused=True,
                refusal_reason="NO_APPROVED_CONTENT",
                citations=[],
                decision=None,
                checks=checks,
                context_pack="",
                retrieval_meta=meta,
                as_of=as_of,
            )
        checks.append(
            GuardrailCheck(
                id="CONTEXT-TOPIC",
                passed=True,
                message="Key topic terms are represented in approved passages",
            )
        )

        used = self._select_passages(result.passages, filters)
        citations = [self._citation(passage) for passage in used]
        answer = self._compose(used, request.market, request.audience)
        output_checks, grounding, output_passed = verify_answer(
            answer, used, [citation.citation_id for citation in citations]
        )
        checks.extend(output_checks)
        meta["grounding_score"] = grounding
        meta["citation_count"] = len(citations)
        meta["sections"] = [f"{p.asset_id}#{p.section_id}" for p in used]
        if not output_passed:
            meta["blocked_checks"] = [check.id for check in output_checks if not check.passed]
            return self._finish(
                request=request,
                trace_id=trace_id,
                started=started,
                answer=REFUSAL_MESSAGES["OUTPUT_GUARDRAIL"],
                refused=True,
                refusal_reason="OUTPUT_GUARDRAIL",
                citations=[],
                decision=None,
                checks=checks,
                context_pack="",
                retrieval_meta=meta,
                as_of=as_of,
            )

        decision = self._decision_for(used[0], filters)
        if decision is not None:
            meta["policy_outcome"] = decision.outcome.value
            meta["policy_score"] = decision.score
        context_pack = self._context_pack(used)
        return self._finish(
            request=request,
            trace_id=trace_id,
            started=started,
            answer=answer,
            refused=False,
            refusal_reason=None,
            citations=citations,
            decision=decision,
            checks=checks,
            context_pack=context_pack,
            retrieval_meta=meta,
            as_of=as_of,
        )

    def _select_passages(
        self, passages: list[RetrievedPassage], filters: SearchFilters
    ) -> list[RetrievedPassage]:
        selected = list(passages[:2])
        if selected:
            safety = self.index.safety_passage(selected[0].asset_id, filters)
            if safety is not None and not any(
                p.asset_id == safety.asset_id and p.section_id == safety.section_id
                for p in selected
            ):
                selected.append(safety)
        return selected

    def _topic_covered(
        self, question: str, passages: list[RetrievedPassage]
    ) -> tuple[bool, set[str]]:
        brand_tokens: set[str] = set()
        for asset in self.store.list_models("asset", Asset):
            brand_tokens.update(tokenize(asset.brand))
            brand_tokens.update(tokenize(asset.title.split(" ")[0]))
        informative = set(tokenize(question)) - GENERIC_TERMS - brand_tokens
        if not informative:
            return True, set()
        indexed: set[str] = set()
        for passage in passages:
            indexed.update(tokenize(f"{passage.heading} {passage.text}"))
        expansion = set(self.taxonomy.expand(question))
        new_terms = expansion - set(tokenize(question))
        matched = bool(informative.intersection(indexed)) or bool(new_terms.intersection(indexed))
        missing = informative - indexed
        return matched, missing

    def _compose(self, passages: list[RetrievedPassage], market: Market, audience: Audience) -> str:
        audience_label = "healthcare professionals" if audience is Audience.HCP else "patients"
        lines = [
            f"Based on current approved content for {market.value} {audience_label}:",
            "",
        ]
        used_indices: set[int] = set()
        for index, passage in enumerate(passages, start=1):
            sentences = [
                sentence.strip()
                for sentence in SENTENCE_RE.split(passage.text)
                if len(tokenize(sentence)) >= 4
            ]
            if not sentences:
                continue
            lines.append(f"- {sentences[0]} [{index}]")
            used_indices.add(index)
        for index, passage in enumerate(passages, start=1):
            sentences = [
                sentence.strip()
                for sentence in SENTENCE_RE.split(passage.text)
                if len(tokenize(sentence)) >= 4
            ]
            if index in used_indices and len(sentences) > 1 and len(used_indices) <= 4:
                lines.append(f"- {sentences[1]} [{index}]")
        lines.extend(
            [
                "",
                "Safety note: This response is limited to approved promotional content and is "
                "not medical advice. Confirm clinical decisions with the current approved label "
                "and the relevant review board.",
                "",
                "Sources: "
                + "; ".join(
                    f"[{index}] {passage.title} v{passage.asset_version} "
                    f"({passage.section_id})"
                    for index, passage in enumerate(passages, start=1)
                ),
            ]
        )
        return "\n".join(lines)

    def _context_pack(self, passages: list[RetrievedPassage]) -> str:
        blocks = []
        for index, passage in enumerate(passages, start=1):
            blocks.append(
                "\n".join(
                    [
                        f"[{index}] {passage.title} - {passage.heading}",
                        (
                            f"asset={passage.asset_id} version={passage.asset_version} "
                            f"market={passage.market.value} audience={passage.audience.value} "
                            f"channel={passage.channel.value} approved={passage.approved_at.date()} "
                            f"expires={passage.expires_at.date()} hash={passage.content_hash[:16]}"
                        ),
                        passage.text,
                    ]
                )
            )
        return "\n\n".join(blocks)

    def _citation(self, passage: RetrievedPassage) -> Citation:
        return Citation(
            citation_id=f"{passage.asset_id}@{passage.asset_version}#{passage.section_id}",
            asset_id=passage.asset_id,
            asset_version=passage.asset_version,
            section_id=passage.section_id,
            title=passage.title,
            excerpt=passage.text[:700],
            deep_link=f"/#lineage/{passage.asset_id}",
            content_hash=passage.content_hash,
            approved_at=passage.approved_at,
            expires_at=passage.expires_at,
            market=passage.market,
            audience=passage.audience,
            channel=passage.channel,
            claim_ids=passage.claim_ids,
        )

    def _decision_for(
        self, passage: RetrievedPassage, filters: SearchFilters
    ) -> PolicyDecision | None:
        experience = self._experience_for(passage, filters)
        try:
            return self.policies.evaluate(
                passage.asset_id,
                filters.market,
                filters.audience,
                passage.channel,
                experience_id=experience.id if experience else None,
                now=filters.as_of,
            )
        except Exception:
            return None

    def _experience_for(
        self, passage: RetrievedPassage, filters: SearchFilters
    ) -> Experience | None:
        for experience in self.store.list_models("experience", Experience):
            if (
                experience.market is filters.market
                and experience.audience is filters.audience
                and experience.channel is passage.channel
                and experience.status is ExperienceStatus.LIVE
            ):
                return experience
        return None

    def _finish(
        self,
        *,
        request: AskRequest,
        trace_id: str,
        started: float,
        answer: str,
        refused: bool,
        refusal_reason: str | None,
        citations: list[Citation],
        decision: PolicyDecision | None,
        checks: list[GuardrailCheck],
        context_pack: str,
        retrieval_meta: dict[str, Any],
        as_of: datetime,
    ) -> AskResponse:
        latency_ms = round((time.perf_counter() - started) * 1000, 3)
        response = AskResponse(
            trace_id=trace_id,
            question=request.question,
            answer=answer,
            refused=refused,
            refusal_reason=refusal_reason,
            citations=citations,
            decision=decision,
            checks=checks,
            context_pack=context_pack,
            latency_ms=latency_ms,
            generated_at=as_of,
            model=MODEL_NAME,
            retrieval_meta=retrieval_meta,
        )
        event = self.store.append_event(
            event_type="ai.answered",
            subject_type="ai_trace",
            subject_id=trace_id,
            actor="governed-assistant",
            occurred_at=as_of,
            trace_id=trace_id,
            payload={
                "question": redact_pii(request.question),
                "market": request.market.value,
                "audience": request.audience.value,
                "channel": request.channel.value if request.channel else None,
                "refused": refused,
                "refusal_reason": refusal_reason,
                "citations": [citation.citation_id for citation in citations],
                "checks": {check.id: check.passed for check in checks},
                "model": MODEL_NAME,
                "grounding": retrieval_meta.get("grounding_score"),
            },
        )
        self.store.save_ai_trace(
            trace_id=trace_id,
            question=redact_pii(request.question),
            market=request.market.value,
            audience=request.audience.value,
            channel=request.channel.value if request.channel else None,
            refused=refused,
            answer=answer,
            citations=[citation.model_dump(mode="json") for citation in citations],
            checks=[check.model_dump(mode="json") for check in checks],
            latency_ms=latency_ms,
            model=MODEL_NAME,
            ledger_event_id=event.id,
        )
        return response


def redact_for_storage(text: str) -> str:
    return re.sub(r"\s+", " ", redact_pii(text)).strip()
