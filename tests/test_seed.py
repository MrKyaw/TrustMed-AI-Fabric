from datetime import UTC, datetime

from trustmed_fabric.seed import seed_store
from trustmed_fabric.store import Store

ANCHOR = datetime(2026, 6, 15, 12, 0, tzinfo=UTC)


def test_seed_is_deterministic(tmp_path) -> None:
    database_path = tmp_path / "seed.db"
    first = Store(database_path)
    result = seed_store(first, now=ANCHOR)
    first.close()

    second = Store(database_path)
    assert second.count("asset") == result["assets"]
    assert second.event_count() == result["ledger_events"]
    assert second.verify_ledger()["valid"] is True
    second.close()


def test_seed_does_not_duplicate(tmp_path) -> None:
    database_path = tmp_path / "seed2.db"
    database = Store(database_path)
    first = seed_store(database, now=ANCHOR)
    second = seed_store(database, now=ANCHOR)
    assert first["seeded"] is True
    assert second["seeded"] is False
    database.close()
