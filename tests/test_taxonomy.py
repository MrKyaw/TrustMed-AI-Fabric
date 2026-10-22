from trustmed_fabric.fixtures import taxonomy_pack
from trustmed_fabric.models import TaxonomyTerm
from trustmed_fabric.taxonomy import Taxonomy


def test_taxonomy_empty_raises() -> None:
    import pytest

    from trustmed_fabric.errors import ValidationError

    with pytest.raises(ValidationError):
        Taxonomy(version="1", terms=[])


def test_taxonomy_as_list_sorted(seeded_store) -> None:
    from trustmed_fabric.seed import load_taxonomy

    taxonomy = load_taxonomy()
    rows = taxonomy.as_list()
    assert rows == sorted(rows, key=lambda row: row["id"])
    assert taxonomy.version == taxonomy_pack()["version"]
    assert len(rows) == len(taxonomy_pack()["terms"])
    assert all(isinstance(TaxonomyTerm.model_validate(row), TaxonomyTerm) for row in rows)
