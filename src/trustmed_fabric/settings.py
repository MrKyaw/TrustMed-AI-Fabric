"""Environment-driven settings with safe local defaults."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from trustmed_fabric.store import Store


@dataclass(frozen=True)
class Settings:
    db_path: str = "data/trustmed.db"
    api_key: str | None = None
    host: str = "127.0.0.1"
    port: int = 8080
    report_dir: str = "reports"
    auto_seed: bool = True

    @classmethod
    def from_env(cls) -> Settings:
        return cls(
            db_path=os.environ.get("TRUSTMED_DB_PATH", "data/trustmed.db"),
            api_key=os.environ.get("TRUSTMED_API_KEY") or None,
            host=os.environ.get("TRUSTMED_HOST", "127.0.0.1"),
            port=int(os.environ.get("TRUSTMED_PORT", "8080")),
            report_dir=os.environ.get("TRUSTMED_REPORT_DIR", "reports"),
            auto_seed=os.environ.get("TRUSTMED_AUTO_SEED", "1") == "1",
        )

    @property
    def report_path(self) -> Path:
        return Path(self.report_dir) / "eval-report.json"


def build_store(settings: Settings | None = None) -> Store:
    active = settings or Settings.from_env()
    return Store(active.db_path)
