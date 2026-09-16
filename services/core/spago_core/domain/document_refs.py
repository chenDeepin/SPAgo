"""Why a measurement does — or does not — carry a source-declared document.

The product's central relation is "this compound was reported in this document"
(AGENTS.md §1), and the number of measurements that can be linked to a patent is a
*measurement of the source*, not a property of the compound. A record whose
document the source never returned must therefore not read the same as one whose
document declares no patent — the first is "we could not ask", the second is "the
source has nothing here", and the third is "the source declares none at all".

The vocabulary below is the shared language for that, used by the adapter that
diagnoses it, the retrieval row that stores the tally
(`source_retrievals.reference_counts`, migration 0016), the API that serves it and
the UI that renders it. Codes are stored, so they are stable strings, not labels.

Buckets are **disjoint** and ordered by the strength of what was found: a record
lands in exactly one, which makes ``sum(counts) == number of records`` a checkable
invariant rather than a hope. A record that carries a patent *and* a DOI is counted
as ``patent_declared``; its DOI is still stored on its own measurement row, so the
summary loses nothing a reader cannot open.
"""
from __future__ import annotations

from typing import Iterable, Protocol

PATENT_DECLARED = "patent_declared"
DOI_ONLY = "doi_only"
PMID_ONLY = "pmid_only"
#: The document was retrieved and declares no patent, DOI or PMID. The reference
#: exists; it just carries none of the three identifiers.
NO_REFERENCE_ON_DOCUMENT = "no_reference_on_document"
#: The source's own row carried no reference at all (adapters whose source states
#: the reference inline, rather than behind a second lookup).
NO_REFERENCE_FROM_SOURCE = "no_reference_from_source"
#: A document id was cited, the source answered, and it does not know that id.
DOCUMENT_UNKNOWN_TO_SOURCE = "document_unknown_to_source"
#: The request bound stopped the lookup before this document was asked for. A
#: configuration fact, reported rather than rounded into "no patent".
DOCUMENT_NOT_RETRIEVED_BOUND = "document_not_retrieved_bound"
#: A lookup failed (source outage) before this document was resolved.
DOCUMENT_NOT_RETRIEVED_FAILURE = "document_not_retrieved_failure"
#: The record carries no document identifier, so there was nothing to resolve.
ACTIVITY_WITHOUT_DOCUMENT = "activity_without_document"

#: Ordered strongest-first; the order is the order a reader wants them.
DOCUMENT_REFERENCE_STATUSES: tuple[str, ...] = (
    PATENT_DECLARED,
    DOI_ONLY,
    PMID_ONLY,
    NO_REFERENCE_ON_DOCUMENT,
    NO_REFERENCE_FROM_SOURCE,
    DOCUMENT_UNKNOWN_TO_SOURCE,
    DOCUMENT_NOT_RETRIEVED_BOUND,
    DOCUMENT_NOT_RETRIEVED_FAILURE,
    ACTIVITY_WITHOUT_DOCUMENT,
)

#: The subset that means "no reference is attached", i.e. the answer to "why do
#: the rest not have a patent". Everything else is a reference that was found.
MISSING_REFERENCE_STATUSES: frozenset[str] = frozenset(
    {
        NO_REFERENCE_ON_DOCUMENT,
        NO_REFERENCE_FROM_SOURCE,
        DOCUMENT_UNKNOWN_TO_SOURCE,
        DOCUMENT_NOT_RETRIEVED_BOUND,
        DOCUMENT_NOT_RETRIEVED_FAILURE,
        ACTIVITY_WITHOUT_DOCUMENT,
    }
)

#: One-line meanings for a reader (API/CLI text). The UI keeps its own labels so
#: the wire format stays codes.
DOCUMENT_REFERENCE_MEANINGS: dict[str, str] = {
    PATENT_DECLARED: "the source's document declares a patent publication number",
    DOI_ONLY: "the document declares a DOI but no patent number",
    PMID_ONLY: "the document declares a PubMed id but no patent or DOI",
    NO_REFERENCE_ON_DOCUMENT: "the document was retrieved and declares no identifier",
    NO_REFERENCE_FROM_SOURCE: "the source row carried no reference at all",
    DOCUMENT_UNKNOWN_TO_SOURCE: "the source does not know the cited document id",
    DOCUMENT_NOT_RETRIEVED_BOUND: "the configured lookup bound was reached first",
    DOCUMENT_NOT_RETRIEVED_FAILURE: "the lookup failed before this document",
    ACTIVITY_WITHOUT_DOCUMENT: "the record cites no document",
}


class _HasDeclaredReferences(Protocol):
    """The fields a record can carry a reference in (structural, not nominal)."""

    document_patent_number: str | None
    document_doi: str | None
    document_pmid: str | None
    document_ref: str | None


def declared_reference_status(record: _HasDeclaredReferences) -> str:
    """The strongest reference a record carries, judged from its own fields.

    Used for adapters that state the reference on the row (no second lookup), and
    as the fallback when an adapter did not stamp an outcome.
    """
    if record.document_patent_number:
        return PATENT_DECLARED
    if record.document_doi:
        return DOI_ONLY
    if record.document_pmid:
        return PMID_ONLY
    if record.document_ref:
        return NO_REFERENCE_ON_DOCUMENT
    return NO_REFERENCE_FROM_SOURCE


def document_reference_counts(records: Iterable[_HasDeclaredReferences]) -> dict[str, int]:
    """Disjoint tally of what happened to each record's document reference.

    A record's own stamped outcome wins (an adapter that performed a lookup knows
    more than the fields alone); otherwise the fields decide. Zero-count buckets
    are omitted so a stored tally stays small, and the counts are returned in the
    vocabulary's order. An unknown status is a programming error and raises rather
    than becoming a bucket no reader can interpret.
    """
    counts: dict[str, int] = {}
    for record in records:
        status = getattr(record, "document_reference_status", None) or declared_reference_status(
            record
        )
        if status not in DOCUMENT_REFERENCE_STATUSES:
            raise ValueError(
                f"Unknown document-reference status {status!r}; expected one of "
                f"{', '.join(DOCUMENT_REFERENCE_STATUSES)}."
            )
        counts[status] = counts.get(status, 0) + 1
    return {status: counts[status] for status in DOCUMENT_REFERENCE_STATUSES if status in counts}
