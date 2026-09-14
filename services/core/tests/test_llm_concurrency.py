"""In-flight concurrency contract: same content → 409, over the per-process
cap → 429, cleanup in finally. Uses fake blocking providers (no HTTP)."""
from __future__ import annotations

import json
import threading
import uuid
from pathlib import Path

import pytest
from spago_core.domain import ProvenanceState

from spago_core.db import run_migrations
from spago_core.seed import seed
from spago_core.services import ai
from conftest import _family_id


class FakeBlockingProvider:
    """Blocks inside generate until the test releases it."""

    name = "llm-fake"
    provenance_state = ProvenanceState.LLM_INFERRED

    def __init__(self, model: str, release: threading.Event, started: threading.Event):
        self.model = model
        self.endpoint_fingerprint = "fake"
        self._release = release
        self._started = started

    def generate(self, snapshot):
        self._started.set()
        self._release.wait(timeout=5)
        from spago_core.adapters.llm import ProviderOutput

        return ProviderOutput(
            content=json.dumps(
                {
                    "paragraphs": [
                        {"text": "Summary.", "fact_refs": [snapshot["family"]["ref"]]}
                    ],
                    "limitations": [],
                }
            ),
            finish_reason="stop",
            tool_calls=False,
            usage=None,
            model=self.model,
        )


@pytest.fixture(scope="module")
def c_engine(pg_engine, fixture_dir: Path, migrations_dir: Path):
    run_migrations(pg_engine, migrations_dir)
    seed(pg_engine, fixture_dir, migrations_dir)
    return pg_engine


def test_same_content_409_and_cap_429(c_engine):
    engine = c_engine
    fid = _family_id(engine)
    ai.clear_inflight()
    release = threading.Event()
    started = threading.Barrier(1)

    results = {}
    errors = {}

    def worker(name, model):
        provider = FakeBlockingProvider(model, release, threading.Event())
        try:
            results[name] = ai.summarize_family(engine, fid, mode="llm", llm_provider=provider)
        except Exception as exc:  # noqa: BLE001
            errors[name] = exc

    def wait_inflight(n: int) -> bool:
        for _ in range(100):
            with ai._INFLIGHT_LOCK:
                if len(ai._INFLIGHT) >= n:
                    return True
            threading.Event().wait(0.05)
        return False

    # Two distinct contents fill the per-process cap of 2.
    threads = [threading.Thread(target=worker, args=("first", "model-a")),
               threading.Thread(target=worker, args=("second", "model-b"))]
    for th in threads:
        th.start()
    assert wait_inflight(2), "blocked workers never registered"

    # Same content as an in-flight key → 409.
    dup = threading.Thread(target=worker, args=("dup", "model-a"))
    dup.start()
    dup.join(timeout=5)
    assert isinstance(errors.get("dup"), ai.ContentInFlightError)

    # A third distinct content while 2 are in flight → 429.
    third = threading.Thread(target=worker, args=("third", "model-c"))
    third.start()
    third.join(timeout=5)
    assert isinstance(errors.get("third"), ai.ProviderBusyError)

    # Release: both blocked calls complete, distinct rows persisted.
    release.set()
    for th in threads:
        th.join(timeout=10)
    assert results["first"]["cached"] is False
    assert results["second"]["cached"] is False
    assert results["first"]["analysis_id"] != results["second"]["analysis_id"]
    ai.clear_inflight()
