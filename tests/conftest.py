"""Shared pytest fixtures for TrustMed AI Fabric."""

from __future__ import annotations

from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from trustmed_fabric.api import create_app
from trustmed_fabric.service import FabricService
from trustmed_fabric.store import Store

ANCHOR = datetime(2026, 6, 15, 12, 0, tzinfo=UTC)


@pytest.fixture
def tmp_db(tmp_path: Path) -> Path:
    return tmp_path / "trustmed-test.db"


@pytest.fixture
def store(tmp_db: Path) -> Iterator[Store]:
    database = Store(tmp_db)
    yield database
    database.close()


@pytest.fixture
def seeded_store(store: Store) -> Store:
    from trustmed_fabric.seed import seed_store

    seed_store(store, now=ANCHOR)
    return store


@pytest.fixture
def service(tmp_db: Path) -> FabricService:
    database = Store(tmp_db)
    instance = FabricService(database, auto_seed=True, report_path=tmp_db.parent / "reports" / "eval-report.json", now=ANCHOR)
    yield instance
    instance.store.close()


@pytest.fixture
def client(service: FabricService) -> TestClient:
    app = create_app(service=service, api_key=None)
    return TestClient(app)


@pytest.fixture
def authed_client(tmp_db: Path) -> TestClient:
    database = Store(tmp_db)
    instance = FabricService(database, auto_seed=True, report_path=tmp_db.parent / "reports" / "eval-report.json", now=ANCHOR)
    app = create_app(service=instance, api_key="secret-key")
    return TestClient(app)
