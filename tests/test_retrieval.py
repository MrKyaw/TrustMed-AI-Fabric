from datetime import UTC, datetime

from trustmed_fabric.models import Audience, Channel, Market
from trustmed_fabric.retrieval import SearchFilters


def test_retrieval_returns_approved_passages(service) -> None:
    result = service.index.search(
        "progression-free survival",
        SearchFilters(market=Market.US, audience=Audience.HCP, channel=Channel.WEB, as_of=datetime(2026, 6, 15, tzinfo=UTC)),
        limit=4,
    )
    assert result.passages
    assert all(passage.market == Market.US for passage in result.passages)
    assert "ONC-HCP-DA-001" in {passage.asset_id for passage in result.passages}


def test_retrieval_excludes_unapproved_assets(service) -> None:
    result = service.index.search(
        "unapproved social post",
        SearchFilters(market=Market.US, audience=Audience.PATIENT, as_of=datetime(2026, 6, 15, tzinfo=UTC)),
        limit=8,
    )
    assert "ONC-PAT-SOC-006" not in {passage.asset_id for passage in result.passages}


def test_retrieval_tokenizer_stems() -> None:
    from trustmed_fabric.retrieval import tokenize

    assert "surviv" not in tokenize("survival")
    assert "progression" in tokenize("progression")
    assert "approved" not in tokenize("approved")
