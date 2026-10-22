"""Versioned taxonomy registry with synonym-aware query expansion."""

from __future__ import annotations

from collections.abc import Iterable

from trustmed_fabric.errors import ValidationError
from trustmed_fabric.models import Asset, AssetType, PolicyFinding, Severity, TaxonomyTerm

CONTENT_TYPE_TAG = {
    AssetType.DETAIL_AID: "content_type:detail-aid",
    AssetType.LANDING_PAGE: "content_type:landing-page",
    AssetType.EMAIL: "content_type:email",
    AssetType.BANNER: "content_type:banner",
    AssetType.VIDEO: "content_type:video",
    AssetType.SOCIAL_POST: "content_type:social-post",
}

REQUIRED_DIMENSIONS = ("therapeutic_area", "audience", "content_type", "market")


class Taxonomy:
    def __init__(self, version: str, terms: Iterable[TaxonomyTerm]) -> None:
        self.version = version
        self.terms = {term.id: term for term in terms}
        if not self.terms:
            raise ValidationError("taxonomy must contain at least one term")
        self._synonyms: dict[str, set[str]] = {}
        for term in self.terms.values():
            for synonym in [term.label, *term.synonyms, term.id.split(":", 1)[1]]:
                self._synonyms.setdefault(synonym.lower(), set()).add(term.id)

    def validate_asset(self, asset: Asset) -> list[PolicyFinding]:
        findings: list[PolicyFinding] = []
        seen: set[str] = set()
        for tag in asset.tags:
            if tag in seen:
                findings.append(
                    PolicyFinding(
                        code="TAX-DUPLICATE",
                        policy_id="TAX-001",
                        severity=Severity.WARNING,
                        message=f"Duplicate taxonomy tag {tag!r}",
                        remediation="Deduplicate the asset metadata before publication.",
                        field="tags",
                    )
                )
            seen.add(tag)
            term = self.terms.get(tag)
            if term is None:
                findings.append(
                    PolicyFinding(
                        code="TAX-UNKNOWN",
                        policy_id="TAX-001",
                        severity=Severity.BLOCKER,
                        message=f"Unknown taxonomy tag {tag!r}",
                        remediation="Map the value to an active taxonomy term.",
                        field="tags",
                    )
                )
            elif term.status != "ACTIVE":
                findings.append(
                    PolicyFinding(
                        code="TAX-DEPRECATED",
                        policy_id="TAX-001",
                        severity=Severity.BLOCKER,
                        message=f"Taxonomy tag {tag!r} is deprecated",
                        remediation="Replace the deprecated term with its approved successor.",
                        field="tags",
                    )
                )

        expected = {
            f"therapeutic_area:{asset.therapeutic_area.lower()}": "therapeutic_area",
            f"audience:{asset.audience.value.lower()}": "audience",
            CONTENT_TYPE_TAG[asset.asset_type]: "content_type",
            f"market:{asset.market.value.lower()}": "market",
        }
        present_dimensions = {
            tag.split(":", 1)[0] for tag in asset.tags if ":" in tag and tag in self.terms
        }
        missing_dimensions = [d for d in REQUIRED_DIMENSIONS if d not in present_dimensions]
        if missing_dimensions:
            findings.append(
                PolicyFinding(
                    code="TAX-MISSING-DIMENSION",
                    policy_id="TAX-002",
                    severity=Severity.BLOCKER,
                    message="Missing required taxonomy dimensions: " + ", ".join(missing_dimensions),
                    remediation="Tag the asset with all required dimensions before review.",
                    field="tags",
                )
            )
        for tag, dimension in expected.items():
            if tag not in seen:
                findings.append(
                    PolicyFinding(
                        code="TAX-MISMATCH",
                        policy_id="TAX-003",
                        severity=Severity.BLOCKER,
                        message=f"Asset field for {dimension} is not represented by tag {tag!r}",
                        remediation="Align structured fields and taxonomy tags; do not fork metadata.",
                        field="tags",
                    )
                )
        return findings

    def expand(self, text: str) -> set[str]:
        """Return extra search tokens from matching labels and synonyms."""

        haystack = f" {text.lower()} "
        additions: set[str] = set()
        for synonym, ids in self._synonyms.items():
            if f" {synonym} " in haystack or f" {synonym}s " in haystack:
                additions.update(synonym.split())
                for term_id in ids:
                    term = self.terms[term_id]
                    additions.update(term.label.lower().split())
                    for value in term.synonyms:
                        additions.update(value.lower().split())
                    additions.add(term.id.split(":", 1)[1].replace("-", " "))
        return additions

    def by_dimension(self, dimension: str) -> list[TaxonomyTerm]:
        return sorted(
            (term for term in self.terms.values() if term.dimension == dimension),
            key=lambda t: t.label,
        )

    def as_list(self) -> list[dict[str, object]]:
        return [term.model_dump(mode="json") for term in sorted(self.terms.values(), key=lambda t: t.id)]
