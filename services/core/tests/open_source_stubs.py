"""Shared stubs for the ONLINE-00 open-source adapter tests.

The adapters take an injectable client, so tests drive them with recorded
payloads (`data/fixtures/open_sources/`) instead of the network. Failures are
expressed the same way the real client expresses them — by raising
`SourceUnavailableError` — so the failure-handling paths are genuinely covered.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

import pytest

from spago_core.adapters.http import SourceUnavailableError

REPO_ROOT = Path(__file__).resolve().parents[3]
OPEN_SOURCE_FIXTURES = REPO_ROOT / "data" / "fixtures" / "open_sources"


def load_fixture(name: str) -> dict:
    return json.loads((OPEN_SOURCE_FIXTURES / name).read_text())


class StubSourceClient:
    """A `SourceClient`-shaped stub keyed by URL fragment.

    `routes` maps a substring of the request URL to either a payload, or a
    `SourceUnavailableError` to raise (or a callable returning either). The
    first matching route wins, so tests state their intent directly.
    """

    def __init__(self, routes: dict[str, object], source_name: str = "stub") -> None:
        self.routes = routes
        self.source_name = source_name
        self.calls: list[tuple[str, dict]] = []

    def get_json(self, url: str, params: dict | None = None):
        self.calls.append((url, params or {}))
        for fragment, value in self.routes.items():
            if fragment in url:
                resolved = value(self.calls[-1]) if callable(value) and not isinstance(value, dict) else value
                if isinstance(resolved, Exception):
                    raise resolved
                return resolved
        raise SourceUnavailableError(self.source_name, f"no stub route for {url}")

    def close(self) -> None:  # pragma: no cover - symmetry with SourceClient
        return None


@pytest.fixture(scope="session")
def open_source_fixtures() -> Path:
    return OPEN_SOURCE_FIXTURES


class StubActivityAdapter:
    """A source adapter that returns fixed `ActivityRecord`s.

    Used where the *rule* under test is about how records from more than one
    source are combined — for example that one upstream experiment recorded in
    two databases is flagged as a duplicate rather than counted as independent
    corroboration. The recorded live payloads cannot exercise that, because the
    live BindingDB REST path supplies no document reference at all.
    """

    source_name = "stub-activity"

    def __init__(
        self,
        records=None,
        *,
        target_key: str = "CHEMBL_STUB",
        target_type=None,
        status: str = "complete",
        warnings=None,
    ) -> None:
        from spago_core.domain import RetrievalStatus
        from spago_core.adapters.bioactivity_base import ActivityResult
        from spago_core.domain import SourceEnvelope, TargetCandidateEntry, TargetLookupResult

        self._records = list(records or [])
        self._target_entry = TargetCandidateEntry(
            identifier=target_key,
            identifier_kind="chembl_target_id",
            name="stub target",
            target_type=target_type,
            organism="Homo sapiens",
            taxon_id=9606,
        )
        self._target_entry_cls = TargetCandidateEntry
        self._result_cls = ActivityResult
        self._lookup_cls = TargetLookupResult
        self._status = RetrievalStatus(status)

    @property
    def source_version(self) -> str:
        return "stub"

    def targets_for_accession(self, accession: str):
        return self._lookup_cls(
            source_name=self.source_name,
            query=accession,
            status=self._status,
            entries=[self._target_entry],
            total_found=1,
            source_version="stub",
            retrieved_at=datetime.now(timezone.utc),
        )

    def activities(self, target_chembl_id: str, target_type=None):
        return self._activity_result(target_type)

    def load(self, accession: str):
        return self._activity_result(None)

    def _activity_result(self, _target_type):
        from spago_core.adapters.bioactivity_base import ActivityResult
        from spago_core.domain import SourceEnvelope

        return ActivityResult(
            envelope=SourceEnvelope(
                source_name=self.source_name,
                source_version="stub",
                dataset_version="stub:2026-09-15",
                retrieved_at=datetime.now(timezone.utc),
                synthetic=True,
            ),
            records=list(self._records),
            status=self._status.value,
        )
