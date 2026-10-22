"""SQLite persistence with an append-only, hash-chained audit ledger.

SQLite is deliberately chosen: the reference platform is runnable with zero
external services, while the ledger and entity boundaries remain explicit
enough to replace with PostgreSQL and an immutable store in production.
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
import threading
from collections.abc import Iterable
from datetime import datetime
from pathlib import Path
from typing import Any, TypeVar

from pydantic import BaseModel

from trustmed_fabric.canonical import canonical_json
from trustmed_fabric.models import LedgerEvent
from trustmed_fabric.timeutil import ensure_utc, new_id, utcnow

T = TypeVar("T", bound=BaseModel)

SCHEMA = """
CREATE TABLE IF NOT EXISTS entities (
    entity_type TEXT NOT NULL,
    id          TEXT NOT NULL,
    doc         TEXT NOT NULL,
    updated_at  TEXT NOT NULL,
    PRIMARY KEY (entity_type, id)
);
CREATE INDEX IF NOT EXISTS idx_entities_type ON entities(entity_type);

CREATE TABLE IF NOT EXISTS ledger (
    sequence     INTEGER PRIMARY KEY AUTOINCREMENT,
    id           TEXT NOT NULL UNIQUE,
    event_type   TEXT NOT NULL,
    subject_type TEXT NOT NULL,
    subject_id   TEXT NOT NULL,
    occurred_at  TEXT NOT NULL,
    actor        TEXT NOT NULL,
    trace_id     TEXT NOT NULL,
    payload      TEXT NOT NULL,
    prev_hash    TEXT NOT NULL,
    hash         TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_ledger_subject ON ledger(subject_type, subject_id);

CREATE TABLE IF NOT EXISTS edges (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    source      TEXT NOT NULL,
    target      TEXT NOT NULL,
    relation    TEXT NOT NULL,
    event_id    TEXT NOT NULL,
    occurred_at TEXT NOT NULL,
    UNIQUE (source, target, relation, event_id)
);
CREATE INDEX IF NOT EXISTS idx_edges_source ON edges(source);
CREATE INDEX IF NOT EXISTS idx_edges_target ON edges(target);

CREATE TABLE IF NOT EXISTS ai_traces (
    trace_id        TEXT PRIMARY KEY,
    question        TEXT NOT NULL,
    market          TEXT NOT NULL,
    audience        TEXT NOT NULL,
    channel         TEXT,
    refused         INTEGER NOT NULL,
    answer          TEXT NOT NULL,
    citations       TEXT NOT NULL,
    checks          TEXT NOT NULL,
    latency_ms      REAL NOT NULL,
    model           TEXT NOT NULL,
    created_at      TEXT NOT NULL,
    ledger_event_id TEXT
);

CREATE TABLE IF NOT EXISTS idempotency (
    key         TEXT PRIMARY KEY,
    operation   TEXT NOT NULL,
    response    TEXT NOT NULL,
    status_code INTEGER NOT NULL,
    created_at  TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS schema_meta (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
"""

GENESIS_HASH = "0" * 64


def _hash_event(material: dict[str, Any], prev_hash: str) -> str:
    return hashlib.sha256(
        (prev_hash + canonical_json(material)).encode("utf-8")
    ).hexdigest()


def event_material(
    *,
    sequence: int,
    event_id: str,
    event_type: str,
    subject_type: str,
    subject_id: str,
    occurred_at: str,
    actor: str,
    trace_id: str,
    payload: dict[str, Any],
    prev_hash: str,
) -> dict[str, Any]:
    """The exact bytes that a ledger hash commits to."""

    return {
        "sequence": sequence,
        "id": event_id,
        "event_type": event_type,
        "subject_type": subject_type,
        "subject_id": subject_id,
        "occurred_at": occurred_at,
        "actor": actor,
        "trace_id": trace_id,
        "payload": payload,
        "prev_hash": prev_hash,
    }


class Store:
    def __init__(self, path: str | Path = ":memory:") -> None:
        self.path = str(path)
        if self.path != ":memory:":
            Path(self.path).parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self._conn = sqlite3.connect(self.path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        with self._lock:
            if self.path != ":memory:":
                self._conn.execute("PRAGMA journal_mode=WAL")
            self._conn.execute("PRAGMA foreign_keys=ON")
            self._conn.executescript(SCHEMA)
            self._conn.commit()

    def close(self) -> None:
        with self._lock:
            self._conn.close()

    # ------------------------------------------------------------------ entities

    def put(self, entity_type: str, model: BaseModel) -> None:
        payload = model.model_dump(mode="json")
        entity_id = str(payload["id"])
        with self._lock:
            self._conn.execute(
                "INSERT INTO entities(entity_type, id, doc, updated_at) VALUES (?,?,?,?) "
                "ON CONFLICT(entity_type, id) DO UPDATE SET doc=excluded.doc, "
                "updated_at=excluded.updated_at",
                (entity_type, entity_id, canonical_json(payload), utcnow().isoformat()),
            )
            self._conn.commit()

    def put_many(self, entity_type: str, models: Iterable[BaseModel]) -> None:
        rows = []
        now = utcnow().isoformat()
        for model in models:
            payload = model.model_dump(mode="json")
            rows.append((entity_type, str(payload["id"]), canonical_json(payload), now))
        with self._lock:
            self._conn.executemany(
                "INSERT INTO entities(entity_type, id, doc, updated_at) VALUES (?,?,?,?) "
                "ON CONFLICT(entity_type, id) DO UPDATE SET doc=excluded.doc, "
                "updated_at=excluded.updated_at",
                rows,
            )
            self._conn.commit()

    def get(self, entity_type: str, entity_id: str) -> dict[str, Any] | None:
        with self._lock:
            row = self._conn.execute(
                "SELECT doc FROM entities WHERE entity_type=? AND id=?",
                (entity_type, entity_id),
            ).fetchone()
        return json.loads(row["doc"]) if row else None

    def get_model(self, entity_type: str, entity_id: str, model: type[T]) -> T | None:
        doc = self.get(entity_type, entity_id)
        return model.model_validate(doc) if doc is not None else None

    def list_entities(self, entity_type: str) -> list[dict[str, Any]]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT doc FROM entities WHERE entity_type=? ORDER BY id",
                (entity_type,),
            ).fetchall()
        return [json.loads(row["doc"]) for row in rows]

    def list_models(self, entity_type: str, model: type[T]) -> list[T]:
        return [model.model_validate(doc) for doc in self.list_entities(entity_type)]

    def count(self, entity_type: str | None = None) -> int:
        with self._lock:
            if entity_type is None:
                row = self._conn.execute("SELECT COUNT(*) AS n FROM entities").fetchone()
            else:
                row = self._conn.execute(
                    "SELECT COUNT(*) AS n FROM entities WHERE entity_type=?",
                    (entity_type,),
                ).fetchone()
        return int(row["n"])

    def data_version(self) -> str:
        """Cheap cache key for derived indexes."""

        with self._lock:
            row = self._conn.execute(
                "SELECT COUNT(*) AS n, COALESCE(MAX(updated_at), '') AS m FROM entities"
            ).fetchone()
        return f"{row['n']}:{row['m']}"

    # -------------------------------------------------------------------- ledger

    def append_event(
        self,
        *,
        event_type: str,
        subject_type: str,
        subject_id: str,
        actor: str,
        payload: dict[str, Any] | None = None,
        edges: Iterable[dict[str, str]] = (),
        occurred_at: datetime | None = None,
        trace_id: str | None = None,
        event_id: str | None = None,
    ) -> LedgerEvent:
        payload = payload or {}
        occurred = ensure_utc(occurred_at or utcnow()).isoformat()
        trace = trace_id or new_id("trc")
        eid = event_id or new_id("evt")
        with self._lock:
            row = self._conn.execute(
                "SELECT sequence, hash FROM ledger ORDER BY sequence DESC LIMIT 1"
            ).fetchone()
            sequence = int(row["sequence"]) + 1 if row else 1
            prev_hash = str(row["hash"]) if row else GENESIS_HASH
            material = event_material(
                sequence=sequence,
                event_id=eid,
                event_type=event_type,
                subject_type=subject_type,
                subject_id=subject_id,
                occurred_at=occurred,
                actor=actor,
                trace_id=trace,
                payload=payload,
                prev_hash=prev_hash,
            )
            digest = _hash_event(material, prev_hash)
            self._conn.execute(
                "INSERT INTO ledger(sequence, id, event_type, subject_type, subject_id, "
                "occurred_at, actor, trace_id, payload, prev_hash, hash) "
                "VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                (
                    sequence,
                    eid,
                    event_type,
                    subject_type,
                    subject_id,
                    occurred,
                    actor,
                    trace,
                    canonical_json(payload),
                    prev_hash,
                    digest,
                ),
            )
            edge_rows = []
            for edge in edges:
                edge_rows.append(
                    (
                        edge["source"],
                        edge["target"],
                        edge["relation"],
                        eid,
                        occurred,
                    )
                )
            if edge_rows:
                self._conn.executemany(
                    "INSERT OR IGNORE INTO edges(source, target, relation, event_id, occurred_at) "
                    "VALUES (?,?,?,?,?)",
                    edge_rows,
                )
            self._conn.commit()
        return LedgerEvent(
            sequence=sequence,
            id=eid,
            event_type=event_type,
            subject_type=subject_type,
            subject_id=subject_id,
            occurred_at=datetime.fromisoformat(occurred),
            actor=actor,
            trace_id=trace,
            payload=payload,
            prev_hash=prev_hash,
            hash=digest,
        )

    def events(
        self,
        *,
        limit: int = 100,
        after_sequence: int = 0,
        subject_id: str | None = None,
    ) -> list[LedgerEvent]:
        query = "SELECT * FROM ledger WHERE sequence > ?"
        params: list[Any] = [after_sequence]
        if subject_id is not None:
            query += " AND subject_id = ?"
            params.append(subject_id)
        query += " ORDER BY sequence DESC LIMIT ?"
        params.append(limit)
        with self._lock:
            rows = self._conn.execute(query, params).fetchall()
        return [self._row_to_event(row) for row in rows]

    def all_events_ascending(self) -> list[LedgerEvent]:
        with self._lock:
            rows = self._conn.execute("SELECT * FROM ledger ORDER BY sequence ASC").fetchall()
        return [self._row_to_event(row) for row in rows]

    def event_count(self) -> int:
        with self._lock:
            row = self._conn.execute("SELECT COUNT(*) AS n FROM ledger").fetchone()
        return int(row["n"])

    @staticmethod
    def _row_to_event(row: sqlite3.Row) -> LedgerEvent:
        return LedgerEvent(
            sequence=int(row["sequence"]),
            id=str(row["id"]),
            event_type=str(row["event_type"]),
            subject_type=str(row["subject_type"]),
            subject_id=str(row["subject_id"]),
            occurred_at=datetime.fromisoformat(str(row["occurred_at"])),
            actor=str(row["actor"]),
            trace_id=str(row["trace_id"]),
            payload=json.loads(row["payload"]),
            prev_hash=str(row["prev_hash"]),
            hash=str(row["hash"]),
        )

    def verify_ledger(self) -> dict[str, Any]:
        """Recompute the whole chain. Any mutation is detected."""

        events = self.all_events_ascending()
        previous = GENESIS_HASH
        for index, event in enumerate(events, start=1):
            if event.sequence != index:
                return {
                    "valid": False,
                    "events": len(events),
                    "broken_at": event.id,
                    "reason": f"sequence gap: expected {index}, found {event.sequence}",
                }
            if event.prev_hash != previous:
                return {
                    "valid": False,
                    "events": len(events),
                    "broken_at": event.id,
                    "reason": "previous hash does not match the prior record",
                }
            material = event_material(
                sequence=event.sequence,
                event_id=event.id,
                event_type=event.event_type,
                subject_type=event.subject_type,
                subject_id=event.subject_id,
                occurred_at=event.occurred_at.isoformat(),
                actor=event.actor,
                trace_id=event.trace_id,
                payload=event.payload,
                prev_hash=event.prev_hash,
            )
            if _hash_event(material, event.prev_hash) != event.hash:
                return {
                    "valid": False,
                    "events": len(events),
                    "broken_at": event.id,
                    "reason": "record hash does not match its contents",
                }
            previous = event.hash
        return {
            "valid": True,
            "events": len(events),
            "head": previous,
            "broken_at": None,
            "reason": None,
        }

    # --------------------------------------------------------------------- edges

    def edges(self) -> list[dict[str, Any]]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT id, source, target, relation, event_id, occurred_at FROM edges "
                "ORDER BY id ASC"
            ).fetchall()
        return [dict(row) for row in rows]

    # ---------------------------------------------------------------- idempotency

    def get_idempotent(self, key: str) -> dict[str, Any] | None:
        with self._lock:
            row = self._conn.execute(
                "SELECT operation, response, status_code FROM idempotency WHERE key=?", (key,)
            ).fetchone()
        if row is None:
            return None
        return {
            "operation": str(row["operation"]),
            "response": json.loads(str(row["response"])),
            "status_code": row["status_code"],
        }

    def put_idempotent(
        self, key: str, operation: str, response: dict[str, Any], status_code: int
    ) -> None:
        with self._lock:
            self._conn.execute(
                "INSERT OR IGNORE INTO idempotency(key, operation, response, status_code, created_at) "
                "VALUES (?,?,?,?,?)",
                (key, operation, canonical_json(response), status_code, utcnow().isoformat()),
            )
            self._conn.commit()

    # ----------------------------------------------------------------- AI traces

    def save_ai_trace(
        self,
        *,
        trace_id: str,
        question: str,
        market: str,
        audience: str,
        channel: str | None,
        refused: bool,
        answer: str,
        citations: list[dict[str, Any]],
        checks: list[dict[str, Any]],
        latency_ms: float,
        model: str,
        ledger_event_id: str | None = None,
    ) -> None:
        with self._lock:
            self._conn.execute(
                "INSERT OR REPLACE INTO ai_traces(trace_id, question, market, audience, channel, "
                "refused, answer, citations, checks, latency_ms, model, created_at, ledger_event_id) "
                "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (
                    trace_id,
                    question,
                    market,
                    audience,
                    channel,
                    int(refused),
                    answer,
                    canonical_json(citations),
                    canonical_json(checks),
                    latency_ms,
                    model,
                    utcnow().isoformat(),
                    ledger_event_id,
                ),
            )
            self._conn.commit()

    def get_ai_trace(self, trace_id: str) -> dict[str, Any] | None:
        with self._lock:
            row = self._conn.execute(
                "SELECT * FROM ai_traces WHERE trace_id=?", (trace_id,)
            ).fetchone()
        if row is None:
            return None
        result = dict(row)
        result["refused"] = bool(result["refused"])
        result["citations"] = json.loads(result["citations"])
        result["checks"] = json.loads(result["checks"])
        return result

    # --------------------------------------------------------------------- reset

    def reset(self) -> None:
        with self._lock:
            for table in ("edges", "ledger", "entities", "ai_traces", "idempotency"):
                self._conn.execute(f"DELETE FROM {table}")
            self._conn.execute("DELETE FROM sqlite_sequence")
            self._conn.commit()

    def table_counts(self) -> dict[str, int]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT entity_type, COUNT(*) AS n FROM entities GROUP BY entity_type"
            ).fetchall()
            result = {str(row["entity_type"]): int(row["n"]) for row in rows}
            result["ledger_events"] = self.event_count()
            result["edges"] = self._conn.execute("SELECT COUNT(*) AS n FROM edges").fetchone()["n"]
        return result
