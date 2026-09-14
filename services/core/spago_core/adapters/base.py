"""External-source adapter contracts (AGENTS.md §8, PROMPT.md §6).

Adapters are the only components that may know an external source's schema.
They return normalized domain models plus a `SourceEnvelope`, so schema changes
in a source require adapter changes, not application-wide changes.
"""
from __future__ import annotations

from typing import Protocol, runtime_checkable

from spago_core.domain import AdapterResult


@runtime_checkable
class ChemicalPatentSource(Protocol):
    """A source of structure occurrences found in patent documents."""

    source_name: str

    def load(self) -> AdapterResult:
        """Load all available structure occurrences as normalized records."""
        ...


@runtime_checkable
class PatentSource(Protocol):
    """A source of patent bibliographic/family metadata."""

    source_name: str

    def load(self) -> AdapterResult:
        """Load patent documents and family metadata as normalized records."""
        ...
