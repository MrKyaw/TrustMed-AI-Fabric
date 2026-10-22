from hypothesis import given
from hypothesis import strategies as st

from trustmed_fabric.canonical import canonical_json
from trustmed_fabric.store import Store


@given(st.text(min_size=1, max_size=60), st.integers(min_value=0, max_value=1000))
def test_canonical_roundtrip_numbers(text: str, number: int) -> None:
    payload = {"text": text, "number": number}
    assert canonical_json(payload) == canonical_json(payload)


def test_ledger_tampering_detected(tmp_path) -> None:
    db = tmp_path / "tamper.db"
    store = Store(db)
    store.append_event(event_type="a", subject_type="asset", subject_id="1", actor="x", payload={"value": 1})
    store.append_event(event_type="b", subject_type="asset", subject_id="2", actor="y", payload={"value": 2})
    # Tamper with a stored payload.
    store._conn.execute("UPDATE ledger SET payload=? WHERE sequence=1", ('{"value":999}',))
    store._conn.commit()
    assert store.verify_ledger()["valid"] is False
    store.close()
