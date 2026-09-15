"""BindingDB REST adapter (ONLINE-00 B).

BindingDB complements ChEMBL with curated protein–ligand affinity measurements
and, where supplied, their publication provenance. Access is through the
official REST service rather than a manual TSV download, so an end user does
not have to fetch a multi-gigabyte export to look at one target.

Verified against the live service on 2026-09-15:

    GET https://bindingdb.org/rest/getLigandsByUniprot?uniprot=P05231&response=application/json
    -> {"getLindsByUniprotResponse": {"bdb.hit": "9", "bdb.affinities": [
          {"bdb.monomerid": ..., "bdb.smile": "... |r|",
           "bdb.affinity_type": "IC50", "bdb.affinity": " 1.1"}, ...]}}

Two details the service does not state in the payload and that this adapter
therefore refuses to guess:

- **Unit.** The REST endpoint reports no unit; the documented convention for
  `getLigandsByUniprot` is nanomolar, and that is what is recorded. The raw
  value string is preserved verbatim alongside it.
- **Unavailable targets.** Some accessions return an HTML page with HTTP 200
  (observed for P08887). That is recorded as a *failed* retrieval with the
  source named, never as "no measurements exist".

The ligand SMILES carries BindingDB's `|r|` relative-stereo marker; it is
stripped for parsing by `clean_external_smiles` and the removal is noted.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

from spago_core.adapters.bioactivity_base import ActivityRecord, ActivityResult
from spago_core.adapters.http import SourceClient, SourceUnavailableError
from spago_core.chemistry import clean_external_smiles
from spago_core.domain import EvidenceClass, RetrievalStatus, SourceEnvelope

SOURCE_NAME = "bindingdb"
SOURCE_VERSION = "bindingdb-rest"
EXTRACTION_METHOD = "bindingdb_rest_uniprot"

LIGANDS_PATH = "/rest/getLigandsByUniprot"

#: Documented convention for this endpoint (no unit field is returned).
DEFAULT_UNIT = "nM"

#: Affinity type → evidence class. A Kd/Ki is a measured equilibrium constant;
#: an IC50 from this endpoint is inhibition of binding, which stays a measured
#: interaction; an EC50 is a concentration-effect readout (functional).
_AFFINITY_EVIDENCE = {
    "kd": EvidenceClass.MEASURED_DIRECT_BINDING,
    "ki": EvidenceClass.MEASURED_DIRECT_BINDING,
    "ic50": EvidenceClass.MEASURED_DIRECT_BINDING,
    "ec50": EvidenceClass.FUNCTIONAL_EFFECT,
    "k": EvidenceClass.MEASURED_DIRECT_BINDING,
}

_UNPARSEABLE_RELATIONS = {"<", ">", "~", "=", "<=", ">="}


def _split_value(raw: str) -> tuple[Optional[float], str]:
    """BindingDB values arrive as plain numbers, sometimes with a relation."""
    text = (raw or "").strip()
    if not text:
        return None, "="
    relation = "="
    if text[0] in "<>~":
        relation = text[0]
        text = text[1:].strip()
    try:
        return float(text), relation
    except ValueError:
        return None, relation


class BindingDBRestAdapter:
    """Target-led BindingDB retrieval by UniProt accession."""

    source_name = SOURCE_NAME
    extraction_method = EXTRACTION_METHOD

    def __init__(self, client: Optional[SourceClient] = None) -> None:
        self.client = client or SourceClient(
            source_name=SOURCE_NAME,
            base_url="https://bindingdb.org",
            min_interval_s=0.5,
            timeout_s=30.0,
        )

    def load(self, accession: str) -> ActivityResult:
        """Fetch all ligands measured against one UniProt accession."""
        retrieved_at = datetime.now(timezone.utc)
        query = (accession or "").strip()
        warnings: list[str] = []
        records: list[ActivityRecord] = []
        rejection_counts: dict[str, int] = {}
        excluded = 0

        if not query:
            return self._result(
                retrieved_at, [], RetrievalStatus.EMPTY, 0, 0, 0, {},
                ["Empty UniProt accession."],
            )

        try:
            payload = self.client.get_json(
                LIGANDS_PATH,
                params={"uniprot": query, "response": "application/json"},
            )
        except SourceUnavailableError as exc:
            return self._result(
                retrieved_at, [], RetrievalStatus.FAILED, 1, 0, 0, {}, [str(exc)]
            )

        body = payload.get("getLindsByUniprotResponse") or {}
        affinities = body.get("bdb.affinities") or []
        if isinstance(affinities, dict):  # single-hit responses collapse to an object
            affinities = [affinities]

        seen = 0
        for row in affinities:
            seen += 1
            raw_smiles = (row.get("bdb.smile") or "").strip()
            if not raw_smiles:
                excluded += 1
                rejection_counts["missing_structure"] = rejection_counts.get("missing_structure", 0) + 1
                continue
            cleaned, notes = clean_external_smiles(raw_smiles)
            affinity_type = (row.get("bdb.affinity_type") or "").strip() or "unknown"
            value, relation = _split_value(row.get("bdb.affinity"))
            if value is None:
                excluded += 1
                key = "missing_affinity"
                rejection_counts[key] = rejection_counts.get(key, 0) + 1
                continue

            monomer_id = row.get("bdb.monomerid")
            source_record_id = f"bindingdb:{monomer_id}:{affinity_type}"
            records.append(
                ActivityRecord(
                    source_record_id=source_record_id,
                    compound_source_id=cleaned,
                    target_key=f"bindingdb:{query}",
                    target_name=None,
                    assay_key=f"bindingdb:{query}:{affinity_type}:{monomer_id}",
                    assay_type="binding",
                    standard_type=affinity_type,
                    value=value,
                    unit=DEFAULT_UNIT,
                    relation=relation if relation in _UNPARSEABLE_RELATIONS else "=",
                    evidence_class=_AFFINITY_EVIDENCE.get(
                        affinity_type.lower(), EvidenceClass.UNSPECIFIED
                    ),
                    raw_value=str(row.get("bdb.affinity")).strip(),
                    assay_description=(
                        f"BindingDB affinity for UniProt {query}, record {monomer_id} "
                        f"({affinity_type}); unit assumed {DEFAULT_UNIT} by the "
                        "service's documented convention."
                    ),
                    species=None,
                    document_ref=None,
                    source_url=(
                        "https://www.bindingdb.org/rwd/bind/chemsearch/marvin/"
                        f"Monomer.jsp?monomerid={monomer_id}"
                        if monomer_id is not None
                        else None
                    ),
                    source_molecule_id=str(monomer_id) if monomer_id is not None else None,
                    raw_smiles=cleaned,
                )
            )
            if notes:
                warnings.extend(f"{source_record_id}: {note}" for note in notes)

        status = RetrievalStatus.EMPTY if not records else RetrievalStatus.COMPLETE
        warnings.append(
            f"BindingDB returns {body.get('bdb.hit', 'an unstated number of')} hit(s) for "
            f"{query}; the service does not report assay-level context, so species and "
            "construct are unavailable from this path."
        )
        return self._result(
            retrieved_at, records, status, 1, seen, excluded, rejection_counts, warnings
        )

    def _result(
        self,
        retrieved_at: datetime,
        records: list[ActivityRecord],
        status: RetrievalStatus,
        pages: int,
        seen: int,
        excluded: int,
        rejection_counts: dict[str, int],
        warnings: list[str],
    ) -> ActivityResult:
        # A stored measurement must name the source it came from; the target's
        # resolver is UniProt, not BindingDB (ONLINE-06).
        dataset_version = f"bindingdb:{retrieved_at.date().isoformat()}"
        for record in records:
            record.source_name = SOURCE_NAME
            record.source_dataset_version = dataset_version
        return ActivityResult(
            envelope=SourceEnvelope(
                source_name=SOURCE_NAME,
                source_version=SOURCE_VERSION,
                dataset_version=dataset_version,
                retrieved_at=retrieved_at,
                synthetic=False,
                warnings=list(warnings),
            ),
            records=records,
            warnings=list(warnings),
            status=status.value,
            pages_fetched=pages,
            records_seen=seen,
            records_excluded=excluded,
            rejection_counts=rejection_counts,
        )
