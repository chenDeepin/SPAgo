"""Bioactivity source contracts (Milestone 3)."""
from __future__ import annotations

from typing import Protocol, runtime_checkable

from pydantic import BaseModel, Field

from spago_core.domain import SourceEnvelope


class ActivityRecord(BaseModel):
    """A normalized measurement. Values stay as-reported (standard_type, unit,
    relation); cross-assay ranking and selectivity math are intentionally
    absent — assay conditions must match before values are comparable."""

    source_record_id: str
    compound_source_id: str
    target_key: str
    target_name: str | None = None
    assay_key: str
    assay_type: str | None = None
    standard_type: str
    value: float
    unit: str
    relation: str = "="


class ActivityResult(BaseModel):
    envelope: SourceEnvelope
    records: list[ActivityRecord] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)


@runtime_checkable
class BioactivitySource(Protocol):
    """A source of compound-target activity measurements."""

    source_name: str

    def load(self) -> ActivityResult:
        """Load available activity measurements as normalized records."""
        ...
