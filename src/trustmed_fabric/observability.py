"""Small, dependency-free operational metrics registry."""

from __future__ import annotations

import math
import threading
import time
from collections import Counter, deque
from typing import Any


class MetricsRegistry:
    def __init__(self) -> None:
        self.started_at = time.time()
        self._lock = threading.Lock()
        self._requests = 0
        self._errors = 0
        self._by_status: Counter[str] = Counter()
        self._by_path: Counter[str] = Counter()
        self._latencies: deque[float] = deque(maxlen=2048)
        self._asks = 0
        self._refusals = 0

    def record_request(self, path: str, status_code: int, latency_ms: float) -> None:
        with self._lock:
            self._requests += 1
            if status_code >= 400:
                self._errors += 1
            self._by_status[str(status_code)] += 1
            self._by_path[path] += 1
            self._latencies.append(latency_ms)

    def record_answer(self, refused: bool) -> None:
        with self._lock:
            self._asks += 1
            if refused:
                self._refusals += 1

    def snapshot(self) -> dict[str, Any]:
        with self._lock:
            latencies = sorted(self._latencies)
            requests = self._requests
            asks = self._asks
            refusals = self._refusals
        return {
            "uptime_seconds": round(time.time() - self.started_at, 1),
            "requests_total": requests,
            "errors_total": self._errors,
            "status_counts": dict(sorted(self._by_status.items())),
            "top_paths": dict(self._by_path.most_common(10)),
            "latency_ms": {
                "p50": _percentile(latencies, 0.50),
                "p95": _percentile(latencies, 0.95),
                "p99": _percentile(latencies, 0.99),
                "samples": len(latencies),
            },
            "assistant": {
                "answers": asks,
                "refusals": refusals,
                "refusal_rate": round(refusals / asks, 4) if asks else 0.0,
            },
        }


def _percentile(values: list[float], percentile: float) -> float:
    if not values:
        return 0.0
    index = max(0, math.ceil(percentile * len(values)) - 1)
    return round(values[index], 3)
