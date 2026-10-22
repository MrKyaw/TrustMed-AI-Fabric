from datetime import UTC, datetime

from trustmed_fabric.canonical import canonical_json


def test_canonical_json_is_deterministic() -> None:
    payload = {"b": 2, "a": 1, "nested": {"y": "x", "x": "y"}}
    first = canonical_json(payload)
    second = canonical_json(payload)
    assert first == second
    assert first == '{"a":1,"b":2,"nested":{"x":"y","y":"x"}}'


def test_canonical_json_handles_datetimes_and_enums() -> None:
    from enum import StrEnum

    class Color(StrEnum):
        RED = "red"

    value = {"when": datetime(2026, 6, 15, tzinfo=UTC), "color": Color.RED}
    assert "2026-06-15T00:00:00Z" in canonical_json(value)
    assert "red" in canonical_json(value)
