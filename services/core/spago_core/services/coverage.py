"""What SPAgo holds for a publication, from where, and what nobody asked (B-26).

Four independent paths can contribute chemistry to one publication, and until this
module nothing put them side by side:

- the **imported corpus** — a live row in ``current_compound_mentions`` for a stored
  document: an occurrence, the strongest answer this build has;
- a **per-publication source lookup** (B-24) — the compounds a source declares for
  that number, in ``patent_source_lookups`` / ``patent_source_compounds``, whether
  the ask succeeded, came back empty, or failed;
- a **target-led source row** (B-02) — a retrieval for a *target* whose record names
  this publication as its source document (``measurements.document_patent_number``);
- **hand-added rows** (ONLINE-07 / B-25) — a person's own measurements and
  structure-less remarks, in the same corpus of stored rows but a different fact.

The audit is a **read of stored rows only**: no source is called, so it needs no user
action and cannot change what the database holds (AGENTS.md §16). Nothing is stored
either — like the potency class, the report is computed on read so a later retrieval
or import cannot leave a stale status behind (AGENTS.md §11).

Three rules keep it honest:

1. **`not_queried` is not `empty`.** A leg nobody asked is reported as never asked and
   named in ``unqueried``; it never reads as "this publication has nothing".
2. **Legs are never summed.** A declared compound is not a corpus occurrence and a
   hand-added row is not a source's declaration. Counts stay in their own leg, and the
   headline *names* the leg it came from.
3. **A failed ask is not an answer.** A lookup stored as ``failed`` stays visible as
   failed, with the rows it still holds attributed to their last successful retrieval
   (migration 0017's rule), and the headline says the row is not the whole picture.

Matching is :func:`patent_tokens` — the one definition of "the same publication" in
this codebase (B-03) — against the stored document identifiers read in one metadata
pass, exactly as ``services.core._tolerant_matches`` does. Unlike
``services.core.publications_in_corpus`` (a read-only "was *this* number imported?",
which stays exact), the audit is answering a reader's question about a number they
typed, so it tolerates the forms people write and **reports** the stored identifier it
matched instead of rewriting the request.

What this audit cannot see, and says so in ``notes`` rather than implying otherwise:
the loaded corpus is the documents that were imported (the family's true sibling set
needs a bibliographic source, B-22), the operator's licensed bulk snapshot (B-23) is
an access path this report has no per-publication leg for, and a legal/status
register (grant, expiry, litigation) is not a chemistry source and stays out of
scope.
"""
from __future__ import annotations

import csv
import io
from datetime import datetime, timezone
from typing import Any, Iterable, Mapping, Sequence

from sqlalchemy import Engine, text

from spago_core.domain.models import (
    COVERAGE_RULE,
    MAX_COVERAGE_PUBLICATIONS,
    CoverageAnswer,
    CoverageLeg,
    CoverageReport,
    PublicationCoverage,
    USER_SUPPLEMENT_SOURCE,
)
from spago_core.domain.patent_numbers import patent_tokens

#: The rule's text, carried with every report and export so a changed precedence is
#: visible in the artifact rather than hidden in a session.
COVERAGE_RULE_TEXT = (
    "patent-coverage-v1: for each publication, three legs are read from stored rows "
    "only — the imported corpus (live compound mentions of a stored document), what a "
    "source declares (a per-publication lookup from B-24, and target-led rows from "
    "B-02 that name this publication as their source document), and hand-added rows "
    "(ONLINE-07/B-25). The headline is the first that applies, in this order: "
    "'corpus' > 'declared' > 'supplement' > 'proposed' (only unconfirmed rows) > "
    "'empty' (a leg was asked and none holds records) > 'failed' (a leg's ask did not "
    "complete and nothing was found) > 'not_queried' (nothing applicable was asked). "
    "Legs and their counts are never summed: a corpus occurrence, a source-declared "
    "compound and a hand-added row are three different facts. 'asked_empty' and "
    "'failed' are answers; 'not_queried' is not, and every never-asked leg is named in "
    "'unqueried'."
)

#: The state a leg can hold, strongest first. A leg takes the strongest state among
#: its answers, so "asked and failed" can never be reported as "never asked".
_LEG_STATE_ORDER: tuple[str, ...] = (
    "has_records",
    "failed",
    "unconfirmed",
    "asked_empty",
    "not_queried",
)

_DOCUMENT_SQL = """
    SELECT d.id, d.family_id, d.publication_number, d.doc_type, d.dataset_version,
           f.family_key, f.title
    FROM patent_documents d
    JOIN patent_families f ON f.id = d.family_id
"""


class CoverageError(ValueError):
    """The request cannot be answered as asked (empty, over the bound, not a number)."""


# --- request handling --------------------------------------------------------------


def _requested(publications: Iterable[str]) -> list[str]:
    """The requests, trimmed and deduplicated, in the caller's order.

    Deduplicating is not cosmetic: the audit costs a fixed set of bounded queries for
    the whole batch, and asking for one publication twice must not double its row.
    """
    out: list[str] = []
    seen: set[str] = set()
    for raw in publications:
        value = str(raw or "").strip()
        if not value:
            continue
        key = value.casefold()
        if key in seen:
            continue
        seen.add(key)
        out.append(value)
    return out


def _tokens_by_request(requests: Sequence[str]) -> dict[str, list[str]]:
    return {raw: patent_tokens(raw) for raw in requests}


# --- the reads ---------------------------------------------------------------------


def _corpus_documents(
    conn, requests: Sequence[str], tokens_by_request: Mapping[str, list[str]]
) -> dict[str, list[dict[str, Any]]]:
    """Requested number → the stored document(s) that name the same publication.

    Exact first (an indexed, unique comparison — the common case, and the one the
    family view takes because it asks with stored identifiers), then one metadata
    read for whatever missed, compared with :func:`patent_tokens` exactly as
    ``find_patent`` does. A request that matches two stored identifiers keeps both:
    reported, never chosen between (AGENTS.md §10; B-03).
    """
    matched: dict[str, list[dict[str, Any]]] = {raw: [] for raw in requests}
    if not requests:
        return matched
    exact = (
        conn.execute(
            text(_DOCUMENT_SQL + " WHERE d.publication_number = ANY(:raw)"),
            {"raw": list(requests)},
        )
        .mappings()
        .all()
    )
    by_number = {row["publication_number"]: dict(row) for row in exact}
    missing: list[str] = []
    for raw in requests:
        row = by_number.get(raw)
        if row is None:
            missing.append(raw)
        else:
            matched[raw] = [row]
    if not missing:
        return matched

    rows = conn.execute(text(_DOCUMENT_SQL)).mappings().all()
    stored = [(dict(row), set(patent_tokens(row["publication_number"]))) for row in rows]
    for raw in missing:
        tokens = set(tokens_by_request[raw])
        hits = [row for row, row_tokens in stored if tokens & row_tokens]
        matched[raw] = sorted(hits, key=lambda row: row["publication_number"])
    return matched


def _corpus_mentions(conn, document_ids: Sequence[Any]) -> dict[Any, dict[str, int]]:
    """Live mention and compound counts for the documents that were matched."""
    if not document_ids:
        return {}
    rows = (
        conn.execute(
            text(
                """
                SELECT m.document_id,
                       count(*) AS mentions,
                       count(DISTINCT m.compound_id) AS compounds
                FROM current_compound_mentions m
                WHERE m.document_id = ANY(:ids)
                GROUP BY m.document_id
                """
            ),
            {"ids": list(document_ids)},
        )
        .mappings()
        .all()
    )
    return {row["document_id"]: dict(row) for row in rows}


def _declared_lookups(conn, tokens: Sequence[str]) -> dict[str, list[dict[str, Any]]]:
    """Stored per-publication source lookups, token → rows (one per source)."""
    if not tokens:
        return {}
    rows = (
        conn.execute(
            text(
                """
                SELECT l.publication_number AS token, l.source_name, l.status,
                       l.match_rule, l.source_version, l.dataset_version,
                       l.retrieved_at, l.records_seen, l.records_excluded,
                       (SELECT count(*) FROM patent_source_compounds c
                         WHERE c.lookup_id = l.id) AS records,
                       (SELECT count(DISTINCT c.compound_id)
                          FROM patent_source_compounds c
                         WHERE c.lookup_id = l.id) AS compounds,
                       (SELECT max(c.retrieved_at) FROM patent_source_compounds c
                         WHERE c.lookup_id = l.id) AS rows_retrieved_at
                FROM patent_source_lookups l
                WHERE l.publication_number = ANY(:tokens)
                ORDER BY l.source_name
                """
            ),
            {"tokens": list(tokens)},
        )
        .mappings()
        .all()
    )
    out: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        out.setdefault(row["token"], []).append(dict(row))
    return out


def _target_led_rows(conn, tokens: Sequence[str]) -> dict[str, list[dict[str, Any]]]:
    """Rows a *target-led* retrieval stored whose record names this publication.

    These are a source's declaration like a per-publication lookup is, but reached
    from the other end: they exist because a target was retrieved, not because anyone
    asked about this publication. They stay their own answer for that reason — and
    the hand-added rows are excluded, because "the source says so" and "a person added
    it" are different facts (AGENTS.md §10).
    """
    if not tokens:
        return {}
    rows = (
        conn.execute(
            text(
                """
                SELECT m.document_patent_number AS token, m.source_name,
                       count(*) AS records,
                       count(DISTINCT m.compound_id) AS compounds,
                       count(DISTINCT a.target_id) AS targets,
                       min(m.dataset_version) AS dataset_version,
                       min(m.retrieved_at) AS retrieved_at,
                       max(m.retrieved_at) AS rows_retrieved_at
                FROM measurements m
                LEFT JOIN assays a ON a.id = m.assay_id
                WHERE m.retracted_at IS NULL
                  AND m.source_name <> :supplement
                  AND m.document_patent_number = ANY(:tokens)
                GROUP BY m.document_patent_number, m.source_name
                ORDER BY m.source_name
                """
            ),
            {"tokens": list(tokens), "supplement": USER_SUPPLEMENT_SOURCE},
        )
        .mappings()
        .all()
    )
    out: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        out.setdefault(row["token"], []).append(dict(row))
    return out


def _declared_compounds(conn, tokens: Sequence[str]) -> dict[str, int]:
    """Distinct compounds the declared leg holds, per token, across both paths.

    One grouped query instead of summing per-answer distinct counts: the same compound
    can be declared by a lookup and named by a target-led row, and it must count once.
    """
    if not tokens:
        return {}
    rows = (
        conn.execute(
            text(
                """
                SELECT token, count(*) AS compounds FROM (
                    SELECT l.publication_number AS token, c.compound_id AS compound_id
                      FROM patent_source_compounds c
                      JOIN patent_source_lookups l ON l.id = c.lookup_id
                     WHERE l.publication_number = ANY(:tokens)
                    UNION
                    SELECT m.document_patent_number AS token, m.compound_id
                      FROM measurements m
                     WHERE m.retracted_at IS NULL
                       AND m.source_name <> :supplement
                       AND m.document_patent_number = ANY(:tokens)
                ) declared
                GROUP BY token
                """
            ),
            {"tokens": list(tokens), "supplement": USER_SUPPLEMENT_SOURCE},
        )
        .mappings()
        .all()
    )
    return {row["token"]: int(row["compounds"]) for row in rows}


def _hand_added_rows(conn, tokens: Sequence[str]) -> dict[str, dict[str, int]]:
    """Hand-added measurements and remarks, per token, in one grouped read.

    Both tables are written by the supplement paths (ONLINE-07 one-row entry and the
    B-25 bundle). The remark table holds rows without a structure; its rows are counted
    as records and never as compounds, so a structure-less remark cannot inflate a
    compound count (AGENTS.md §11).
    """
    if not tokens:
        return {}
    rows = (
        conn.execute(
            text(
                """
                SELECT token,
                       count(*) AS records,
                       count(*) FILTER (
                           WHERE provenance_state = 'user_curated'
                       ) AS confirmed,
                       count(DISTINCT compound_id) AS compounds,
                       count(DISTINCT target_id) AS targets
                FROM (
                    SELECT m.document_patent_number AS token, m.provenance_state,
                           m.compound_id, a.target_id
                      FROM measurements m
                      LEFT JOIN assays a ON a.id = m.assay_id
                     WHERE m.source_name = :source
                       AND m.retracted_at IS NULL
                       AND m.document_patent_number = ANY(:tokens)
                    UNION ALL
                    SELECT r.patent_number, r.provenance_state, NULL, r.target_id
                      FROM target_supplement_remarks r
                     WHERE r.retracted_at IS NULL
                       AND r.patent_number = ANY(:tokens)
                ) hand_added
                GROUP BY token
                """
            ),
            {"tokens": list(tokens), "source": USER_SUPPLEMENT_SOURCE},
        )
        .mappings()
        .all()
    )
    return {row["token"]: dict(row) for row in rows}


# --- leg and headline construction -------------------------------------------------


def _strongest_state(states: Iterable[str]) -> str:
    """The strongest state among a leg's answers, by the rule's fixed order.

    The states are materialized first: `in` against a one-shot iterable would
    consume it on the first comparison and silently report the weakest state
    (found by a test whose only answer was `asked_empty`).
    """
    present = set(states)
    for state in _LEG_STATE_ORDER:
        if state in present:
            return state
    return "not_queried"


def _answers_for(
    bucket: Mapping[str, list[dict[str, Any]]], tokens: Sequence[str]
) -> list[dict[str, Any]]:
    """The stored rows of one bucket that belong to a request, in the request's order."""
    return [row for token in tokens for row in bucket.get(token, [])]


def _print_time(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, datetime):
        return value.astimezone(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    return str(value)


def _corpus_leg(request: str, documents: Sequence[Mapping[str, Any]], mentions: Mapping) -> CoverageLeg:
    if not documents:
        return CoverageLeg(
            leg="corpus",
            state="not_queried",
            detail=(
                f"no document in the loaded corpus is stored under {request}; the corpus "
                "can only report the documents that were imported"
            ),
            answers=[
                CoverageAnswer(
                    kind="corpus",
                    state="not_queried",
                    status="not_in_corpus",
                    detail=f"no corpus document matches {request}",
                )
            ],
        )

    primary = documents[0]
    counts = mentions.get(primary["id"]) or {}
    found = int(counts.get("mentions", 0))
    compounds = int(counts.get("compounds", 0))
    extra = [row["publication_number"] for row in documents[1:]]
    answer_detail = (
        f"corpus document {primary['publication_number']} holds {found} live compound "
        f"mention(s) of {compounds} compound(s) (corpus dataset "
        f"{primary['dataset_version']}; retracted mentions excluded)"
        if found
        else (
            f"corpus document {primary['publication_number']} is imported and holds no "
            f"live compound mention (corpus dataset {primary['dataset_version']})"
        )
    )
    if extra:
        answer_detail += (
            "; the request also matches "
            + ", ".join(extra)
            + " — reported, not merged"
        )
    return CoverageLeg(
        leg="corpus",
        state="has_records" if found else "asked_empty",
        records=found,
        compounds=compounds,
        detail=answer_detail,
        answers=[
            CoverageAnswer(
                kind="corpus",
                state="has_records" if found else "asked_empty",
                status="occurrence" if found else "imported_without_compounds",
                records=found,
                compounds=compounds,
                dataset_version=primary["dataset_version"],
                detail=answer_detail,
            )
        ],
    )


def _lookup_answer(row: Mapping[str, Any]) -> CoverageAnswer:
    status = row["status"]
    records = int(row["records"] or 0)
    compounds = int(row["compounds"] or 0)
    if records:
        state = "has_records"
    elif status == "failed":
        state = "failed"
    else:
        state = "asked_empty"
    when = _print_time(row["retrieved_at"])
    if state == "has_records" and status == "failed":
        detail = (
            f"{row['source_name']} could not answer on the last attempt "
            f"({when}); the {records} declared row(s) shown were retrieved "
            f"{_print_time(row['rows_retrieved_at'])}"
        )
    elif state == "has_records":
        detail = (
            f"{row['source_name']} declares {records} record(s) covering {compounds} "
            f"compound(s) for this number (status {status}, retrieved {when})"
        )
    elif state == "failed":
        detail = (
            f"{row['source_name']} could not answer for this number: the lookup is "
            f"stored as failed ({when}) and holds no rows"
        )
    else:
        detail = (
            f"{row['source_name']} returned no declared compound for this number "
            f"(status {status}, retrieved {when})"
        )
    return CoverageAnswer(
        kind="patent_source_lookup",
        source_name=row["source_name"],
        state=state,
        status=status,
        records=records,
        compounds=compounds,
        match_rule=row["match_rule"],
        source_version=row["source_version"],
        dataset_version=row["dataset_version"],
        retrieved_at=row["retrieved_at"],
        rows_retrieved_at=row["rows_retrieved_at"],
        detail=detail,
    )


def _target_led_answer(row: Mapping[str, Any]) -> CoverageAnswer:
    records = int(row["records"] or 0)
    compounds = int(row["compounds"] or 0)
    detail = (
        f"{records} stored {row['source_name']} row(s) from a target-led retrieval name "
        f"this publication as their source document, covering {compounds} compound(s) "
        f"across {int(row['targets'] or 0)} target(s) (retrieved "
        f"{_print_time(row['retrieved_at'])})"
    )
    return CoverageAnswer(
        kind="target_led_source",
        source_name=row["source_name"],
        state="has_records",
        status="declared_for_target",
        records=records,
        compounds=compounds,
        dataset_version=row["dataset_version"],
        retrieved_at=row["retrieved_at"],
        rows_retrieved_at=row["rows_retrieved_at"],
        detail=detail,
    )


def _declared_leg(
    lookups: Sequence[Mapping[str, Any]],
    target_led: Sequence[Mapping[str, Any]],
    compounds: int,
    tokens: Sequence[str],
) -> CoverageLeg:
    answers = [_lookup_answer(row) for row in lookups] + [
        _target_led_answer(row) for row in target_led
    ]
    if not answers:
        return CoverageLeg(
            leg="declared",
            state="not_queried",
            detail=(
                "no source has ever been asked about this number: neither a "
                "per-publication lookup nor a target-led retrieval is stored for it"
                if tokens
                else (
                    "the request carries no publication number, so no stored lookup "
                    "can be compared with it"
                )
            ),
            answers=[],
        )
    records = sum(answer.records for answer in answers)
    return CoverageLeg(
        leg="declared",
        state=_strongest_state(answer.state for answer in answers),
        records=records,
        compounds=compounds if records else 0,
        detail="; ".join(answer.detail for answer in answers),
        answers=answers,
    )


def _supplement_leg(counts: Mapping[str, Any] | None, tokens: Sequence[str]) -> CoverageLeg:
    records = int((counts or {}).get("records", 0) or 0)
    confirmed = int((counts or {}).get("confirmed", 0) or 0)
    compounds = int((counts or {}).get("compounds", 0) or 0)
    targets = int((counts or {}).get("targets", 0) or 0)
    unconfirmed = records - confirmed
    if not records:
        return CoverageLeg(
            leg="supplement",
            state="not_queried",
            detail=(
                "no hand-added row cites this publication"
                if tokens
                else (
                    "the request carries no publication number, so no hand-added row "
                    "can be compared with it"
                )
            ),
            answers=[],
        )
    if confirmed:
        state = "has_records"
        detail = (
            f"{confirmed} hand-added row(s) citing this publication are confirmed in a "
            f"target's investigation"
        )
        if unconfirmed:
            detail += (
                f"; {unconfirmed} more were proposed and await a person's confirmation "
                "(not counted as coverage)"
            )
    else:
        state = "unconfirmed"
        detail = (
            f"{unconfirmed} row(s) cite this publication but no person has confirmed "
            "them yet: a proposal is readable and is not coverage (B-25)"
        )
    return CoverageLeg(
        leg="supplement",
        state=state,
        records=records,
        compounds=compounds,
        unconfirmed_records=unconfirmed,
        targets=targets,
        detail=detail,
        answers=[
            CoverageAnswer(
                kind="hand_added",
                state=state,
                status="user_curated" if confirmed else "awaiting_confirmation",
                records=records,
                compounds=compounds,
                unconfirmed_records=unconfirmed,
                detail=detail,
            )
        ],
    )


def _headline(legs: Sequence[CoverageLeg]) -> tuple[str, list[str]]:
    """The headline status and the legs that were never asked.

    Order is the rule's: a stored record of any kind outranks a proposal, a proposal
    outranks "asked and nothing", a failed ask outranks an empty one (it did not
    complete), and a leg nobody asked leaves the row `not_queried` — never `empty`.
    """
    by_leg = {leg.leg: leg for leg in legs}
    unqueried = [leg.leg for leg in legs if leg.state == "not_queried"]
    corpus = by_leg.get("corpus")
    declared = by_leg.get("declared")
    supplement = by_leg.get("supplement")

    if corpus is not None and corpus.state == "has_records":
        return "corpus", unqueried
    if declared is not None and declared.state == "has_records":
        return "declared", unqueried
    if supplement is not None and supplement.state == "has_records":
        return "supplement", unqueried
    if supplement is not None and supplement.state == "unconfirmed":
        return "proposed", unqueried
    answered = [leg for leg in legs if leg.state in ("asked_empty", "failed")]
    if not answered:
        return "not_queried", unqueried
    if any(leg.state == "failed" for leg in answered):
        return "failed", unqueried
    return "empty", unqueried


def _ask_did_not_complete(leg: CoverageLeg) -> bool:
    """True when this leg's ask failed, with or without rows left from before.

    A failed attempt that kept the last successful set is still an incomplete
    answer: the rows are real, and the reader must be told the source could not be
    asked this time (migration 0017's rule, read back).
    """
    return leg.state == "failed" or any(answer.status == "failed" for answer in leg.answers)


def _headline_reason(status: str, legs: Sequence[CoverageLeg]) -> str:
    by_leg = {leg.leg: leg for leg in legs}
    if status == "corpus":
        reason = f"the corpus holds compounds for this publication: {by_leg['corpus'].detail}"
    elif status == "declared":
        strongest = next(
            answer
            for answer in by_leg["declared"].answers
            if answer.state == "has_records"
        )
        reason = (
            "the corpus holds no compound mention for this publication; a source "
            f"declares compounds for the number: {strongest.detail}"
        )
    elif status == "supplement":
        reason = (
            "neither the corpus nor a source declares a compound for this publication; "
            f"a person's own rows do: {by_leg['supplement'].detail}"
        )
    elif status == "proposed":
        reason = (
            "nothing confirmed is stored for this publication, and rows a producer "
            f"proposed await review: {by_leg['supplement'].detail}"
        )
    elif status == "failed":
        failed = [leg for leg in legs if leg.state == "failed"]
        reason = (
            "a leg's ask did not complete and no leg holds records, so this row is not "
            "the whole picture: "
            + "; ".join(leg.detail for leg in failed)
        )
    elif status == "empty":
        asked = [leg for leg in legs if leg.state == "asked_empty"]
        reason = (
            "every leg that applies was asked and none of them holds a record or a "
            "compound for this publication: "
            + "; ".join(leg.detail for leg in asked)
        )
    else:
        reason = (
            "nothing applicable was asked about this publication: "
            + "; ".join(leg.detail for leg in legs if leg.state == "not_queried")
        )
    if status in ("corpus", "declared", "supplement", "proposed"):
        # A failed *attempt* is worth naming even when a leg still holds rows from a
        # previous successful retrieval: the row must not read as a complete answer.
        incomplete = [leg for leg in legs if _ask_did_not_complete(leg)]
        if incomplete:
            reason += (
                "; an ask did not complete, so this row is not the whole picture: "
                + "; ".join(leg.detail for leg in incomplete)
            )
    return reason


def _row(
    request: str,
    tokens: Sequence[str],
    documents: Sequence[Mapping[str, Any]],
    mentions: Mapping,
    lookups: Sequence[Mapping[str, Any]],
    target_led: Sequence[Mapping[str, Any]],
    declared_compounds: int,
    supplements: Mapping[str, Any] | None,
) -> PublicationCoverage:
    legs = [
        _corpus_leg(request, documents, mentions),
        _declared_leg(lookups, target_led, declared_compounds, tokens),
        _supplement_leg(supplements, tokens),
    ]
    status, unqueried = _headline(legs)
    primary = documents[0] if documents else None
    return PublicationCoverage(
        requested=request,
        matched=primary["publication_number"] if primary else None,
        normalized=list(tokens),
        in_corpus=bool(documents),
        family_id=primary["family_id"] if primary else None,
        family_key=primary["family_key"] if primary else None,
        doc_type=primary["doc_type"] if primary else None,
        ambiguous=[row["publication_number"] for row in documents[1:]],
        status=status,
        status_rule=COVERAGE_RULE,
        status_reason=_headline_reason(status, legs),
        unqueried=unqueried,
        legs=legs,
    )


#: The not-asked/not-seen limits, stated in every report rather than implied.
_REPORT_NOTES = (
    "This audit reads stored rows only: the loaded corpus (the documents that were "
    "imported), stored per-publication source lookups, target-led source rows and "
    "hand-added rows. It calls no source.",
    "The corpus leg can only report documents SPAgo imported. A publication missing "
    "from it was not necessarily never loaded elsewhere; the family's full sibling set "
    "needs a bibliographic source (B-22), and the loaded dataset versions are listed on "
    "the corpus surface.",
    "A licensed bulk snapshot (BindingDB or another operator dataset) is an operator "
    "access path (B-23), not a leg of this audit: the report has no per-publication "
    "snapshot read, so a snapshot hit is neither a corpus occurrence nor a complete "
    "publication scan and is never reported as one.",
    "'not_queried' means nobody asked about that leg. It is not a statement that the "
    "publication has no compounds, and it is never an 'absent' verdict.",
)

#: The headline statuses that name a leg actually holding records. The other three
#: (`empty`, `failed`, `not_queried`) are the absence of an answer, so they are never
#: counted into "holds compounds" — that count is a statement about stored rows, and
#: keeping it here means a surface reads it instead of re-deriving the rule (§11).
_HOLDING_STATUSES = ("corpus", "declared", "supplement", "proposed")


def audit_publications(engine: Engine, publications: Sequence[str]) -> CoverageReport:
    """Audit what SPAgo holds for each publication, in the caller's order.

    One bounded set of grouped reads for the whole batch (never per row, §16/§21):
    the corpus document metadata, the corpus mention counts, the stored per-publication
    lookups, the target-led rows, the declared distinct compounds and the hand-added
    rows. All returned rows are stored facts; nothing here retrieves anything.
    """
    requests = _requested(publications)
    if not requests:
        raise CoverageError("A coverage audit needs at least one publication number.")
    if len(requests) > MAX_COVERAGE_PUBLICATIONS:
        raise CoverageError(
            f"{len(requests)} publications were asked about; one audit covers at most "
            f"{MAX_COVERAGE_PUBLICATIONS} (AGENTS.md §13). Split the list."
        )
    tokens_by_request = _tokens_by_request(requests)
    all_tokens = sorted({token for tokens in tokens_by_request.values() for token in tokens})
    if not all_tokens:
        raise CoverageError(
            "None of the requested values carries a publication number, so there is "
            "nothing to audit."
        )

    with engine.connect() as conn:
        documents = _corpus_documents(conn, requests, tokens_by_request)
        document_ids = [row["id"] for hits in documents.values() for row in hits]
        mentions = _corpus_mentions(conn, document_ids)
        lookups = _declared_lookups(conn, all_tokens)
        target_led = _target_led_rows(conn, all_tokens)
        declared_compounds = _declared_compounds(conn, all_tokens)
        supplements = _hand_added_rows(conn, all_tokens)

    rows: list[PublicationCoverage] = []
    for request in requests:
        tokens = tokens_by_request[request]
        rows.append(
            _row(
                request,
                tokens,
                documents[request],
                mentions,
                _answers_for(lookups, tokens),
                _answers_for(target_led, tokens),
                sum(declared_compounds.get(token, 0) for token in tokens),
                next(
                    (supplements[token] for token in tokens if token in supplements),
                    None,
                ),
            )
        )
    return _assemble(rows, len(requests))


def merge_coverage_reports(reports: Sequence[CoverageReport]) -> CoverageReport:
    """One report from several audited chunks (for a list longer than the bound).

    The bound exists for one *request* (AGENTS.md §13). An operator auditing a
    portfolio runs several bounded audits and reads one report; statuses, totals and
    the failure notes are re-derived from the merged rows rather than copied, so the
    merged report cannot disagree with its own rows — and the bound note is kept only
    where a chunk really was at the bound.
    """
    reports = [report for report in reports if report is not None]
    if not reports:
        raise CoverageError("A coverage audit needs at least one publication number.")
    if len(reports) == 1:
        return reports[0]
    rows = [row for report in reports for row in report.publications]
    return _assemble(rows, max(len(report.publications) for report in reports))


def _assemble(rows: Sequence[PublicationCoverage], requested: int) -> CoverageReport:
    """The report a set of audited rows adds up to (one place, one set of totals)."""
    totals: dict[str, int] = {
        "publications": len(rows),
        "not_fully_asked": sum(1 for row in rows if row.unqueried),
        "failed_legs": sum(
            1 for row in rows for leg in row.legs if _ask_did_not_complete(leg)
        ),
        "ambiguous": sum(1 for row in rows if row.ambiguous),
    }
    for row in rows:
        totals[row.status] = totals.get(row.status, 0) + 1
    totals["holds_records"] = sum(totals.get(status, 0) for status in _HOLDING_STATUSES)

    notes = list(_REPORT_NOTES)
    incomplete = [
        (row.requested, leg)
        for row in rows
        for leg in row.legs
        if _ask_did_not_complete(leg)
    ]
    for requested_number, leg in incomplete:
        notes.append(
            f"An ask did not complete for {requested_number}: {leg.detail}. Re-run the "
            "lookup rather than reading the row as a complete answer."
        )
    if requested >= MAX_COVERAGE_PUBLICATIONS:
        notes.append(
            f"This report is at the audit bound ({MAX_COVERAGE_PUBLICATIONS} "
            "publications). A longer list needs a second report, not a bigger request."
        )

    return CoverageReport(
        rule=COVERAGE_RULE,
        rule_text=COVERAGE_RULE_TEXT,
        generated_at=datetime.now(timezone.utc),
        publications=list(rows),
        totals=totals,
        notes=notes,
    )


# --- rendering ---------------------------------------------------------------------

#: Long form: one row per publication-leg-answer, with the leg's own state and counts
#: beside the answer's, so every number can be re-derived from the file.
COVERAGE_CSV_FIELDS: tuple[str, ...] = (
    "coverage_rule",
    "generated_at",
    "publication_requested",
    "publication_matched",
    "normalized_number",
    "in_corpus",
    "family_key",
    "doc_type",
    "ambiguous",
    "status",
    "status_reason",
    "leg",
    "leg_state",
    "leg_records",
    "leg_compounds",
    "leg_unconfirmed_records",
    "leg_targets",
    "leg_unqueried",
    "leg_detail",
    "answer_kind",
    "answer_source",
    "answer_state",
    "answer_status",
    "answer_records",
    "answer_compounds",
    "answer_unconfirmed_records",
    "answer_match_rule",
    "answer_source_version",
    "answer_dataset_version",
    "answer_retrieved_at",
    "answer_rows_retrieved_at",
    "answer_detail",
)

_LEG_STATE_LABEL = {
    "has_records": "holds records",
    "unconfirmed": "proposed, not confirmed",
    "asked_empty": "asked, no records",
    "failed": "ask failed",
    "not_queried": "never asked",
}


def _leg_summary(leg: CoverageLeg) -> str:
    label = _LEG_STATE_LABEL.get(leg.state, leg.state)
    if leg.leg == "corpus":
        counts = (
            f"{leg.records} mentions / {leg.compounds} compounds" if leg.records else ""
        )
    elif leg.leg == "declared":
        counts = f"{leg.records} declared rows / {leg.compounds} compounds" if leg.records else ""
    else:
        counts = f"{leg.records} rows" if leg.records else ""
        if leg.unconfirmed_records:
            counts += f" ({leg.unconfirmed_records} proposed)"
    return f"{label} · {counts}" if counts else label


def render_coverage_csv(report: CoverageReport) -> str:
    """One row per publication-leg-answer; the rule and the rule's reason per row."""
    generated = report.generated_at.astimezone(timezone.utc).isoformat()
    buf = io.StringIO()
    writer = csv.DictWriter(buf, fieldnames=list(COVERAGE_CSV_FIELDS))
    writer.writeheader()
    for row in report.publications:
        for leg in row.legs:
            answers = leg.answers or [None]
            for answer in answers:
                writer.writerow(
                    {
                        "coverage_rule": report.rule,
                        "generated_at": generated,
                        "publication_requested": row.requested,
                        "publication_matched": row.matched or "",
                        "normalized_number": " ".join(row.normalized),
                        "in_corpus": str(row.in_corpus).lower(),
                        "family_key": row.family_key or "",
                        "doc_type": row.doc_type or "",
                        "ambiguous": " ".join(row.ambiguous),
                        "status": row.status,
                        "status_reason": row.status_reason,
                        "leg": leg.leg,
                        "leg_state": leg.state,
                        "leg_records": leg.records,
                        "leg_compounds": leg.compounds,
                        "leg_unconfirmed_records": leg.unconfirmed_records,
                        "leg_targets": leg.targets,
                        "leg_unqueried": str(leg.leg in row.unqueried).lower(),
                        "leg_detail": leg.detail,
                        "answer_kind": answer.kind if answer else "",
                        "answer_source": (answer.source_name or "") if answer else "",
                        "answer_state": answer.state if answer else "",
                        "answer_status": answer.status if answer else "",
                        "answer_records": answer.records if answer else "",
                        "answer_compounds": answer.compounds if answer else "",
                        "answer_unconfirmed_records": (
                            answer.unconfirmed_records if answer else ""
                        ),
                        "answer_match_rule": (answer.match_rule or "") if answer else "",
                        "answer_source_version": (
                            (answer.source_version or "") if answer else ""
                        ),
                        "answer_dataset_version": (
                            (answer.dataset_version or "") if answer else ""
                        ),
                        "answer_retrieved_at": (
                            _print_time(answer.retrieved_at) if answer else ""
                        ),
                        "answer_rows_retrieved_at": (
                            _print_time(answer.rows_retrieved_at) if answer else ""
                        ),
                        "answer_detail": answer.detail if answer else "",
                    }
                )
    return buf.getvalue()


def render_coverage_markdown(report: CoverageReport) -> str:
    """The operator's readable audit: a summary, the per-publication table, the notes."""
    generated = report.generated_at.astimezone(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    totals = report.totals
    counts = ", ".join(
        f"{status}: {totals[status]}"
        for status in (
            "corpus",
            "declared",
            "supplement",
            "proposed",
            "empty",
            "failed",
            "not_queried",
        )
        if totals.get(status)
    )
    lines = [
        f"# Patent coverage audit ({report.rule})",
        "",
        f"Generated {generated} · {totals.get('publications', 0)} publication(s) · "
        f"{totals.get('holds_records', 0)} holding records · "
        f"{totals.get('not_fully_asked', 0)} with a leg never asked · "
        f"{totals.get('failed_legs', 0)} failed leg(s) · "
        f"{totals.get('ambiguous', 0)} ambiguous match(es)",
        "",
        f"Headlines: {counts or 'none'}",
        "",
        "| publication | status | corpus | declared | supplement | never asked | reason |",
        "| --- | --- | --- | --- | --- | --- | --- |",
    ]
    for row in report.publications:
        legs = {leg.leg: leg for leg in row.legs}
        lines.append(
            "| "
            + " | ".join(
                [
                    f"`{row.matched or row.requested}`"
                    + (f" (asked as {row.requested})" if row.matched and row.matched != row.requested else ""),
                    f"**{row.status}**",
                    _leg_summary(legs["corpus"]),
                    _leg_summary(legs["declared"]),
                    _leg_summary(legs["supplement"]),
                    ", ".join(row.unqueried) or "—",
                    row.status_reason.replace("|", "/"),
                ]
            )
            + " |"
        )
    lines += ["", "## Notes", ""]
    lines += [f"- {note}" for note in report.notes]
    lines += ["", "## Rule", "", report.rule_text, ""]
    return "\n".join(lines)


def coverage_filename(report: CoverageReport, fmt: str) -> str:
    """A filename that names the scope the file covers."""
    if len(report.publications) == 1:
        token = report.publications[0].matched or report.publications[0].requested
        stem = "".join(ch for ch in token if ch.isalnum() or ch in "-_") or "publication"
    else:
        stem = f"{len(report.publications)}-publications"
    return f"spago-coverage-{stem}.{fmt}"
