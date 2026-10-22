"""Deterministic BM25 retrieval over approved content only.

The index contains drafts and expired assets for governance analysis, but the
query path applies approval, version, market, audience and channel filters
before a single term is scored. There is no "search everything then filter the
answer" step: unapproved text never reaches the prompt.
"""

from __future__ import annotations

import math
import re
from collections import Counter
from dataclasses import dataclass, field
from datetime import datetime

from trustmed_fabric.models import (
    ApprovalStatus,
    Asset,
    AssetStatus,
    Audience,
    Channel,
    Claim,
    Market,
    RetrievedPassage,
)
from trustmed_fabric.store import Store
from trustmed_fabric.taxonomy import Taxonomy
from trustmed_fabric.timeutil import ensure_utc, utcnow

TOKEN_RE = re.compile(r"[a-z0-9]+")
SENTENCE_RE = re.compile(r"(?<=[.!?])\s+")

STOPWORDS = {
    "a",
    "about",
    "an",
    "and",
    "any",
    "are",
    "as",
    "at",
    "approved",
    "approval",
    "available",
    "be",
    "been",
    "by",
    "can",
    "content",
    "could",
    "did",
    "do",
    "does",
    "for",
    "from",
    "give",
    "has",
    "have",
    "how",
    "i",
    "in",
    "information",
    "is",
    "it",
    "me",
    "my",
    "of",
    "on",
    "or",
    "our",
    "patient",
    "patients",
    "please",
    "show",
    "summarise",
    "summarize",
    "tell",
    "that",
    "the",
    "their",
    "there",
    "these",
    "this",
    "to",
    "us",
    "use",
    "was",
    "we",
    "were",
    "what",
    "when",
    "where",
    "which",
    "who",
    "why",
    "with",
    "you",
    "your",
}

GENERIC_TERMS = STOPWORDS | {
    "approved",
    "approval",
    "document",
    "documents",
    "email",
    "help",
    "know",
    "need",
    "provide",
    "say",
    "source",
    "sources",
    "study",
}


def tokenize(text: str, *, keep_stopwords: bool = False) -> list[str]:
    raw = TOKEN_RE.findall(text.lower())
    tokens = []
    for token in raw:
        if not keep_stopwords and token in STOPWORDS:
            continue
        if len(token) < 2 and not token.isdigit():
            continue
        tokens.append(_stem(token))
    return tokens


def _stem(token: str) -> str:
    if token.endswith("ies") and len(token) > 4:
        return token[:-3] + "y"
    if token.endswith("sses"):
        return token[:-2]
    if token.endswith("s") and not token.endswith("ss") and len(token) > 3:
        return token[:-1]
    return token


@dataclass(frozen=True)
class SearchFilters:
    market: Market
    audience: Audience
    channel: Channel | None = None
    as_of: datetime = field(default_factory=utcnow)


@dataclass
class SearchResult:
    passages: list[RetrievedPassage]
    eligible_assets: int
    matched_assets: int
    index_version: str
    query_terms: list[str]


@dataclass
class _Doc:
    asset: Asset
    passage: RetrievedPassage
    tf: Counter[str]
    length: int


class RetrievalIndex:
    def __init__(self, store: Store, taxonomy: Taxonomy) -> None:
        self.store = store
        self.taxonomy = taxonomy
        self._claim_cache = {
            claim.id: claim for claim in store.list_models("claim", Claim)
        }
        self._docs: list[_Doc] = []
        self._df: Counter[str] = Counter()
        self._avg_length = 0.0
        self._build()

    def _build(self) -> None:
        assets = self.store.list_models("asset", Asset)
        for asset in assets:
            if asset.approval is None:
                # Drafts never enter the retrieval corpus, even as unapproved text.
                continue
            for section in asset.sections:
                weighted = Counter[str]()
                text_parts = [
                    (asset.title, 3),
                    (asset.summary, 2),
                    (section.heading, 2),
                    (section.body, 1),
                    (" ".join(asset.tags).replace(":", " ").replace("-", " "), 2),
                ]
                for claim_id in section.claim_ids:
                    claim = self._claim_cache.get(claim_id)
                    if claim is not None:
                        text_parts.append((claim.text, 2))
                        text_parts.append((claim.approved_wording, 1))
                for text, weight in text_parts:
                    for token in tokenize(text):
                        weighted[token] += weight
                self._docs.append(
                    _Doc(
                        asset=asset,
                        passage=self._passage(asset, section.id, section.heading, section.body),
                        tf=weighted,
                        length=sum(weighted.values()),
                    )
                )
        for doc in self._docs:
            for token in doc.tf:
                self._df[token] += 1
        self._avg_length = (
            sum(doc.length for doc in self._docs) / len(self._docs) if self._docs else 0.0
        )
        self._n = len(self._docs)

    def _passage(self, asset: Asset, section_id: str, heading: str, body: str) -> RetrievedPassage:
        approval = asset.approval
        assert approval is not None
        return RetrievedPassage(
            asset_id=asset.id,
            asset_version=asset.version,
            section_id=section_id,
            heading=heading,
            text=body,
            score=0.0,
            title=asset.title,
            market=asset.market,
            audience=asset.audience,
            channel=asset.channel,
            claim_ids=next(
                (section.claim_ids for section in asset.sections if section.id == section_id),
                [],
            ),
            content_hash=asset.content_hash,
            approved_at=approval.approved_at,
            expires_at=approval.expires_at,
        )

    @staticmethod
    def eligible(asset: Asset, filters: SearchFilters) -> bool:
        approval = asset.approval
        if asset.status is not AssetStatus.APPROVED or approval is None:
            return False
        if approval.status is not ApprovalStatus.APPROVED:
            return False
        if approval.version != asset.version:
            return False
        if approval.approved_at > filters.as_of or approval.expires_at < filters.as_of:
            return False
        if asset.market is not filters.market or asset.audience is not filters.audience:
            return False
        return not (filters.channel is not None and asset.channel is not filters.channel)

    def search(
        self, query: str, filters: SearchFilters, *, limit: int = 4
    ) -> SearchResult:
        as_of = ensure_utc(filters.as_of)
        active_filters = SearchFilters(
            market=filters.market,
            audience=filters.audience,
            channel=filters.channel,
            as_of=as_of,
        )
        eligible = [doc for doc in self._docs if self.eligible(doc.asset, active_filters)]
        eligible_assets = len({doc.asset.id for doc in eligible})
        query_tokens = tokenize(query)
        expanded = self.taxonomy.expand(query)
        all_terms = list(dict.fromkeys([*query_tokens, *sorted(expanded)]))
        if not all_terms or not eligible:
            return SearchResult(
                passages=[],
                eligible_assets=eligible_assets,
                matched_assets=0,
                index_version=self.version,
                query_terms=all_terms,
            )
        corpus_size = self._n
        scores: list[tuple[float, _Doc]] = []
        for doc in eligible:
            score = 0.0
            for term in all_terms:
                tf = doc.tf.get(term, 0)
                if tf == 0:
                    continue
                df = self._df.get(term, 0)
                idf = math.log(1 + (corpus_size - df + 0.5) / (df + 0.5))
                denominator = tf + 1.5 * (1 - 0.75 + 0.75 * doc.length / (self._avg_length or 1))
                score += idf * (tf * 2.5) / denominator
            if score > 0:
                scores.append((score, doc))
        scores.sort(key=lambda item: (-item[0], item[1].asset.id, item[1].passage.section_id))

        selected: list[tuple[float, _Doc]] = []
        per_asset: Counter[str] = Counter()
        for score, doc in scores:
            if per_asset[doc.asset.id] >= 2:
                continue
            selected.append((score, doc))
            per_asset[doc.asset.id] += 1
            if len(selected) >= limit:
                break
        passages = []
        for score, doc in selected:
            snippet = self._snippet(doc.passage.text, all_terms)
            passages.append(doc.passage.model_copy(update={"score": round(score, 4), "text": snippet}))
        return SearchResult(
            passages=passages,
            eligible_assets=eligible_assets,
            matched_assets=len({passage.asset_id for passage in passages}),
            index_version=self.version,
            query_terms=all_terms,
        )

    def safety_passage(
        self, asset_id: str, filters: SearchFilters
    ) -> RetrievedPassage | None:
        asset = self.store.get_model("asset", asset_id, Asset)
        if asset is None or not self.eligible(asset, filters):
            return None
        for section in asset.sections:
            if section.safety_information:
                return self._passage(asset, section.id, section.heading, section.body)
        return None

    @staticmethod
    def _snippet(text: str, terms: list[str]) -> str:
        sentences = [sentence.strip() for sentence in SENTENCE_RE.split(text) if sentence.strip()]
        if len(sentences) <= 2:
            return text[:900]
        term_set = set(terms)
        ranked = []
        for index, sentence in enumerate(sentences):
            overlap = len(term_set.intersection(tokenize(sentence)))
            ranked.append((overlap, -index, sentence))
        chosen = sorted(sorted(ranked, reverse=True)[:2], key=lambda item: -item[1])
        snippet = " ".join(item[2] for item in chosen)
        return snippet[:900]

    @property
    def version(self) -> str:
        return f"bm25-{self._n}-{int(self._avg_length * 100)}"

    def stats(self) -> dict[str, object]:
        return {
            "sections": len(self._docs),
            "assets": len({doc.asset.id for doc in self._docs}),
            "vocabulary": len(self._df),
            "version": self.version,
        }


def build_index(store: Store, taxonomy: Taxonomy) -> RetrievalIndex:
    return RetrievalIndex(store, taxonomy)
