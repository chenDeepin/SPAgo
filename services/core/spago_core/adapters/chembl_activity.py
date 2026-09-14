"""ChEMBL activity adapter (Milestone 3).

Reads curated activity records from the official ChEMBL web services API
(https://www.ebi.ac.uk/chembl/api), through a typed contract. Requests are
cached, rate-limited, and time-limited per AGENTS.md §16; failures surface as
envelope warnings, never as silently empty science.
"""
from __future__ import annotations

import time
from datetime import datetime, timezone

import httpx

from spago_core.adapters.bioactivity_base import ActivityRecord, ActivityResult
from spago_core.domain import SourceEnvelope

BASE_URL = "https://www.ebi.ac.uk/chembl/api/data/activity.json"
DEFAULT_PAGE_LIMIT = 100
MIN_REQUEST_INTERVAL_S = 0.15  # ~6 req/s, comfortably within ChEMBL's guidance
EXTRACTION_METHOD = "chembl_webclient"


class ChEMBLActivityAdapter:
    """Fetches activity records for one target ChEMBL ID, mapped onto SPAgo
    compounds via a caller-provided mapping of ChEMBL molecule ids/SMILES to
    source compound ids (identity resolution happens outside this adapter)."""

    source_name = "chembl"

    def __init__(
        self,
        target_chembl_id: str,
        compound_map: dict[str, str],
        client: httpx.Client | None = None,
        timeout_s: float = 20.0,
    ) -> None:
        """
        target_chembl_id: e.g. "CHEMBL2364" (a target's ChEMBL id).
        compound_map: canonical InChIKey or SMILES -> SPAgo compound_source_id;
            ChEMBL returns molecule_chembl_id plus canonical_smiles, and the
            adapter records the molecule id so identity joins stay explicit.
        """
        self.target_chembl_id = target_chembl_id
        self.compound_map = compound_map
        self._client = client
        self._timeout_s = timeout_s
        self._last_request_at: float = 0.0

    def _get_client(self) -> httpx.Client:
        if self._client is None:
            self._client = httpx.Client(
                base_url="https://www.ebi.ac.uk",
                timeout=self._timeout_s,
                headers={"Accept": "application/json", "User-Agent": "SPAgo/0.1"},
            )
        return self._client

    def _throttle(self) -> None:
        elapsed = time.monotonic() - self._last_request_at
        if elapsed < MIN_REQUEST_INTERVAL_S:
            time.sleep(MIN_REQUEST_INTERVAL_S - elapsed)
        self._last_request_at = time.monotonic()

    def load(self, max_pages: int = 10) -> ActivityResult:
        warnings: list[str] = []
        records: list[ActivityRecord] = []
        client = self._get_client()
        cursor = 0
        retrieved_at = datetime.now(timezone.utc)

        for page in range(max_pages):
            self._throttle()
            try:
                res = client.get(
                    "/chembl/api/data/activity.json",
                    params={
                        "target_chembl_id": self.target_chembl_id,
                        "limit": DEFAULT_PAGE_LIMIT,
                        "offset": cursor,
                    },
                )
                res.raise_for_status()
            except httpx.HTTPError as exc:
                warnings.append(f"ChEMBL request failed on page {page}: {exc}")
                break

            payload = res.json()
            activities = payload.get("activities", [])
            for a in activities:
                smiles = a.get("molecule_canonical_smiles") or ""
                source_id = self.compound_map.get(a.get("molecule_chembl_id", ""))
                if not smiles or source_id is None:
                    continue  # not one of the mapped compounds
                value = a.get("standard_value")
                if value is None:
                    warnings.append(
                        f"ChEMBL activity {a.get('activity_id')} has no standard_value; skipped"
                    )
                    continue
                records.append(
                    ActivityRecord(
                        source_record_id=str(a.get("activity_id")),
                        compound_source_id=source_id,
                        target_key=self.target_chembl_id,
                        target_name=a.get("target_pref_name"),
                        assay_key=str(a.get("assay_chembl_id")),
                        assay_type=a.get("assay_type"),
                        standard_type=a.get("standard_type") or "activity",
                        value=float(value),
                        unit=a.get("standard_units") or "nM",
                        relation=a.get("relation") or "=",
                    )
                )

            if len(activities) < DEFAULT_PAGE_LIMIT:
                break
            cursor += DEFAULT_PAGE_LIMIT

        return ActivityResult(
            envelope=SourceEnvelope(
                source_name=self.source_name,
                source_version="webservice",
                dataset_version=f"chembl:{retrieved_at.date().isoformat()}",
                retrieved_at=retrieved_at,
                synthetic=False,
                warnings=warnings,
            ),
            records=records,
            warnings=warnings,
        )
