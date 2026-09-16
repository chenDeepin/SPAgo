"""Cohort coverage matrix: what the acceptance targets actually retrieve.

`docs/online-capability.md` §6 requires the coverage matrix to be "re-recorded for
the acceptance targets on the deployed build" before an invited beta, and §8 lists
the coverage matrix as the ONLINE-06 input for the invited cohort. This is the
operator tool for that: it runs a target list through the *shipped* services and
prints the matrix next to each target's potency verdict.

Two modes:

* **read** (default) — report what is stored. Nothing is written, no upstream call
  is made. Use it to re-record coverage on a deployed build whose data is already
  loaded.
* **investigate** (`--investigate --yes`) — resolve each query and run bounded
  retrieval from the open sources, exactly as the product's Run action does. This
  writes `targets`, `source_retrievals`, `target_candidates` and `measurements`
  rows, and it spends upstream requests. It is the only mode that can populate a
  target that was never investigated.

It records; it does not judge. A `failed` source is reported as failed, an `empty`
source as empty, and a target that did not resolve as `not_found` — the three are
never collapsed into "no data". The potency verdict is repeated per target with its
policy version so the matrix can separate "retrieved nothing" from "retrieved a set
with no compound at or below the threshold".

Run (operator tooling):

    # re-record coverage for the acceptance cohort on the current build
    docker compose run --rm -v "$PWD/scripts:/app/scripts:ro" app \
        python /app/scripts/cohort_coverage.py TSLP CD40LG IL-6 IL-6R EGFR \
        --out - > benchmarks/cohort-coverage-<date>.json

    # populate a target first (billed upstream, not by a model)
    docker compose run --rm -v "$PWD/scripts:/app/scripts:ro" app \
        python /app/scripts/cohort_coverage.py CD40LG --investigate --yes

    # measure live how much of a source's data links to a document (B-02): reads
    # the stored ChEMBL scope, calls the source, writes nothing to the database
    docker compose run --rm -v "$PWD/scripts:/app/scripts:ro" app \
        python /app/scripts/cohort_coverage.py TSLP CD40LG EGFR --declarations \
        --out - > benchmarks/reference-declarations-<date>.md
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone

from sqlalchemy import text

from spago_core import __version__
from spago_core.adapters.chembl_discovery import (
    DEFAULT_MAX_ACTIVITIES,
    ChEMBLDiscoveryAdapter,
)
from spago_core.config import get_settings
from spago_core.db.engine import make_engine
from spago_core.domain import (
    DOCUMENT_REFERENCE_MEANINGS,
    DOCUMENT_REFERENCE_STATUSES,
    DOI_ONLY,
    PATENT_DECLARED,
    PMID_ONLY,
    document_reference_counts,
)
from spago_core.services import discovery as discovery_svc
from spago_core.services import targets as targets_svc
from spago_core.services.discovery import EXTERNAL_SOURCES
from spago_core.services.reference import policy_from_settings, reference_verdicts

#: The acceptance cohort named in `docs/online-capability.md` §6, plus the EGFR
#: positive control from `benchmarks/online00-coverage-2026-09-15.md` — a control
#: that must return a large set, so an empty acceptance target cannot be mistaken
#: for a broken adapter.
DEFAULT_COHORT = ("TSLP", "CD40LG", "IL-6", "IL-6R", "EGFR")


def _write_or_print(text_out: str, out: str | None) -> None:
    """One place for the output contract: `-`/absent prints, a path writes."""
    if out == "-" or out is None:
        print(text_out)
        return
    with open(out, "w", encoding="utf-8") as handle:
        handle.write(text_out if text_out.endswith("\n") else text_out + "\n")
    _log(f"wrote {out}")


def _log(message: str = "") -> None:
    print(message, file=sys.stderr, flush=True)


def _investigate(engine, queries, sources) -> dict[str, dict]:
    """Resolve and run bounded retrieval for each query. Writes to the database."""
    resolution = targets_svc.TargetResolutionService()
    discovery = discovery_svc.TargetDiscoveryService()
    outcomes: dict[str, dict] = {}
    for query in queries:
        existing = resolution.find_target(engine, query)
        if existing is not None:
            target = existing
            state = "reused stored scope"
        else:
            outcome = resolution.resolve(engine, query)
            if outcome.target is None:
                outcomes[query] = {
                    "resolution_status": outcome.record.status,
                    "notes": list(outcome.record.notes),
                }
                _log(f"  {query:12s} resolution {outcome.record.status}")
                continue
            target = outcome.target
            state = f"resolved ({outcome.record.status})"
        report = discovery.investigate(engine, target, sources)
        outcomes[query] = {
            "resolution_status": state,
            "target_id": str(report.target_id),
            "target_key": report.target_key,
            "sources": [
                {
                    "source_name": r.source_name,
                    "status": r.status.value if hasattr(r.status, "value") else str(r.status),
                    "records_kept": r.records_kept,
                    "records_seen": r.records_seen,
                }
                for r in report.retrievals
            ],
        }
        kept = ", ".join(
            f"{s['source_name']}={s['status']}({s['records_kept']})" for s in outcomes[query]["sources"]
        )
        _log(f"  {query:12s} {state}; {kept}")
    return outcomes


def _stored_chembl_scope(engine, target) -> list[str]:
    """The ChEMBL target ids the stored investigation retrieved through.

    Read from the retrieval's own recorded query rather than re-planned, so the
    declaration measurement answers for exactly the scope this deployment
    investigated (and spends the same upstream requests it did).
    """
    with engine.connect() as conn:
        rows = conn.execute(
            text(
                """
                SELECT query FROM source_retrievals
                WHERE target_id = :tid AND source_name = 'chembl'
                ORDER BY retrieved_at DESC
                """
            ),
            {"tid": target.id},
        ).all()
    for (query,) in rows:
        payload = query if isinstance(query, dict) else json.loads(query or "{}")
        ids = [str(value) for value in (payload.get("target_chembl_ids") or []) if value]
        if ids:
            return ids
    return []


def _declarations(engine, queries, max_activities: int) -> dict[str, dict]:
    """Live, read-only: how many records a source can link to a document (B-02).

    For each query it takes the ChEMBL target ids the stored investigation used,
    fetches bounded activities through the shipped adapter, and tallies what
    happened to each *kept* record's document reference. Nothing is written and no
    row is created: this measures the source, it does not re-run the product.

    A record reachable through two target definitions (a single protein and an
    interaction) is counted once, by activity id — the same rule the service
    applies when it de-duplicates.
    """
    resolution = targets_svc.TargetResolutionService()
    adapter = ChEMBLDiscoveryAdapter(max_activities=max_activities)
    outcomes: dict[str, dict] = {}
    for query in queries:
        target = resolution.find_target(engine, query)
        if target is None:
            outcomes[query] = {
                "status": "not investigated",
                "note": (
                    "No stored target, so the scope to measure is unknown. Run "
                    "--investigate first; this is not a zero-declaration result."
                ),
            }
            _log(f"  {query:12s} not investigated — no stored scope to measure")
            continue
        scope = _stored_chembl_scope(engine, target)
        if not scope:
            outcomes[query] = {
                "status": "no stored ChEMBL scope",
                "target_key": target.target_key,
                "note": (
                    "The stored investigations recorded no ChEMBL target id "
                    "(the source was empty or failed); there is nothing to measure."
                ),
            }
            _log(f"  {query:12s} no stored ChEMBL scope")
            continue

        by_activity: dict[str, object] = {}
        seen = excluded = pages = 0
        warnings: list[str] = []
        statuses: list[str] = []
        for chembl_id in scope:
            result = adapter.activities(chembl_id)
            seen += result.records_seen
            excluded += result.records_excluded
            pages += result.pages_fetched
            warnings.extend(result.warnings)
            statuses.append(result.status)
            for record in result.records:
                by_activity.setdefault(record.source_record_id, record)
        counts = document_reference_counts(by_activity.values())
        outcomes[query] = {
            "status": "measured",
            "target_key": target.target_key,
            "target_name": target.name,
            "uniprot_accession": target.uniprot_accession,
            "chembl_target_ids": scope,
            "source": "chembl",
            "source_statuses": statuses,
            "pages_fetched": pages,
            "records_seen": seen,
            "records_kept": len(by_activity),
            "records_excluded": excluded,
            "reference_counts": counts,
            "warnings": warnings,
            "bounds": {
                "max_activities_per_target": adapter.max_activities,
                "max_document_lookups": adapter.max_document_lookups,
            },
        }
        patent = counts.get(PATENT_DECLARED, 0)
        _log(
            f"  {query:12s} {len(by_activity)} kept record(s); "
            f"{patent} carry a source-declared patent"
        )
    return outcomes


def _declaration_totals(measured: dict[str, dict]) -> dict[str, int]:
    totals: dict[str, int] = {}
    for outcome in measured.values():
        for status, count in (outcome.get("reference_counts") or {}).items():
            totals[status] = totals.get(status, 0) + count
    return {status: totals[status] for status in DOCUMENT_REFERENCE_STATUSES if status in totals}


def _render_declarations(measured, generated_at, build, bounds) -> str:
    """Markdown for the live declaration measurement, one section per query."""
    totals = _declaration_totals(measured)
    kept = sum(int(o.get("records_kept") or 0) for o in measured.values() if o.get("status") == "measured")
    lines = [
        "# Source-declared document references — live measurement",
        "",
        f"Measured {generated_at} from the running build (`api_version` {build}) by",
        "`scripts/cohort_coverage.py --declarations` through the shipped ChEMBL",
        "adapter. Live upstream calls; nothing was written to the database.",
        "",
        f"Bounds in force: {bounds['max_activities_per_target']} activities per ChEMBL",
        f"target id, {bounds['max_document_lookups']} document-metadata request(s).",
        "",
        "A record's document reference is what the source declared. It is **not**",
        "evidence that the compound occurs in that document in SPAgo's corpus, and it",
        "is not a statement about patent coverage either way.",
        "",
        "## Totals",
        "",
        f"{kept} kept record(s) measured.",
        "",
        "| Outcome | Records | Meaning |",
        "| --- | --- | --- |",
    ]
    for status, count in totals.items():
        lines.append(f"| `{status}` | {count} | {DOCUMENT_REFERENCE_MEANINGS.get(status, '')} |")
    lines.append("")
    for query, outcome in measured.items():
        lines += [f"## {query}", ""]
        if outcome.get("status") != "measured":
            lines += [f"**Not measured** — {outcome.get('note')}", ""]
            continue
        counts = outcome["reference_counts"]
        linked = sum(counts.get(key, 0) for key in (PATENT_DECLARED, DOI_ONLY, PMID_ONLY))
        lines += [
            f"{outcome.get('target_key')} — {outcome.get('target_name') or 'unnamed'} · "
            f"UniProt {outcome.get('uniprot_accession') or '—'}",
            "",
            f"ChEMBL target ids: {', '.join(outcome['chembl_target_ids'])} · "
            f"status {', '.join(outcome['source_statuses'])} · "
            f"{outcome['pages_fetched']} page(s)",
            "",
            f"{outcome['records_seen']} record(s) returned, {outcome['records_excluded']} "
            f"excluded (no structure or no numeric value), **{outcome['records_kept']} kept**; "
            f"{linked} of them linked to a document.",
            "",
            "| Outcome | Records |",
            "| --- | --- |",
        ]
        for status in DOCUMENT_REFERENCE_STATUSES:
            if counts.get(status):
                lines.append(f"| `{status}` | {counts[status]} |")
        lines.append("")
        for warning in outcome.get("warnings") or []:
            lines.append(f"> {warning}")
        if outcome.get("warnings"):
            lines.append("")
    lines += [
        "---",
        "",
        "`document_not_retrieved_bound` and `document_not_retrieved_failure` are facts about",
        "this retrieval, not about the compounds: the lookup stopped before those documents",
        "were resolved. They must never be rendered as \"no patent\".",
        "",
    ]
    return "\n".join(lines)


def _build_rows(engine):
    """The stored matrix, joined to each target's verdict, through shipped reads."""
    matrix = discovery_svc.coverage_matrix(engine)
    targets = {t.id: t for t in targets_svc.TargetResolutionService().list_targets(engine)}
    policy = policy_from_settings(get_settings())
    verdicts = reference_verdicts(engine, list(targets.values()), policy)
    rows = []
    for row in matrix:
        verdict = verdicts.get(row["target_id"])
        rows.append(
            {
                **{k: (str(v) if hasattr(v, "hex") else v) for k, v in row.items()},
                "reference": (
                    {
                        "qualifies": verdict.qualifies,
                        "reason": verdict.reason,
                        "policy_version": verdict.policy.version,
                        "threshold_nM": verdict.policy.threshold_nm,
                        "min_compounds": verdict.policy.min_compounds,
                        "modality_scope": verdict.policy.modality_scope,
                        "compounds": verdict.compounds,
                        "compounds_active": verdict.compounds_active,
                        "compounds_weak": verdict.compounds_weak,
                        "compounds_unknown": verdict.compounds_unknown,
                        "compounds_not_applicable": verdict.compounds_not_applicable,
                        "measurements": verdict.measurements,
                        "records_without_structure": verdict.records_without_structure,
                        "supplement_remarks": verdict.supplement_remarks,
                        "active_compounds_outside_scope": verdict.active_compounds_outside_scope,
                    }
                    if verdict is not None
                    else None
                ),
            }
        )
    return rows, targets


def _render(rows, queries, resolution, generated_at, build) -> str:
    """Markdown for a human record. Every number is copied, none is computed."""
    lines = [
        "# Cohort coverage matrix",
        "",
        f"Generated {generated_at} from the running build (`api_version` {build}).",
        "Produced by `scripts/cohort_coverage.py` through the shipped read paths"
        " (`coverage_matrix`, `reference_verdicts`), not by hand.",
        "",
        f"Requested cohort: {', '.join(queries)}",
        "",
    ]
    by_target: dict[str, list[dict]] = {}
    for row in rows:
        by_target.setdefault(row["target_key"], []).append(row)
    for query in queries:
        matched = [key for key in by_target if key.lower() == query.lower()]
        if not matched:
            matched = [
                key
                for key in by_target
                if any(
                    (row.get("gene_symbol") or "").lower() == query.lower()
                    or (row.get("uniprot_accession") or "").lower() == query.lower()
                    for row in by_target[key]
                )
            ]
        if not matched:
            note = resolution.get(query, {}).get("resolution_status", "no stored investigation")
            lines += [
                f"## {query}",
                "",
                f"**Not in the stored matrix** — {note}. A target with no stored"
                " retrieval has no coverage to report; this is not a zero result.",
                "",
            ]
            continue
        key = matched[0]
        rows_for = by_target[key]
        head = rows_for[0]
        lines += [
            f"## {key}" + (f" — {head.get('target_name')}" if head.get("target_name") else ""),
            "",
            f"UniProt {head.get('uniprot_accession') or '—'} · "
            f"{head.get('target_type') or '—'} · {head.get('organism') or '—'}",
            "",
            "| Source | Status | Seen | Kept | Excluded | Candidates | Small-molecule | Version |",
            "| --- | --- | --- | --- | --- | --- | --- | --- |",
        ]
        for row in sorted(rows_for, key=lambda r: r["source_name"]):
            lines.append(
                f"| {row['source_name']} | {row['status']} | {row['records_seen']} | "
                f"{row['records_kept']} | {row['records_excluded']} | {row['candidates']} | "
                f"{row['small_molecule_candidates']} | "
                f"{row.get('dataset_version') or row.get('source_version') or '—'} |"
            )
        verdict = head.get("reference")
        lines.append("")
        # B-02: how much of what this source returned can be linked to a document,
        # and why the rest cannot. A retrieval recorded before the tally existed
        # says so instead of showing a zero.
        for row in sorted(rows_for, key=lambda r: r["source_name"]):
            counts = row.get("reference_counts") or {}
            if not counts:
                lines.append(
                    f"Reference coverage — {row['source_name']}: not recorded for this "
                    "run (it predates the tally); that is not \"none declared\"."
                )
                continue
            linked = sum(
                counts.get(key, 0) for key in ("patent_declared", "doi_only", "pmid_only")
            )
            parts = ", ".join(
                f"{count} {status.replace('_', ' ')}"
                for status, count in counts.items()
                if count
            )
            lines.append(
                f"Reference coverage — {row['source_name']}: {linked} of "
                f"{row['records_kept']} kept record(s) linked to a document ({parts})."
            )
        lines.append("")
        if verdict:
            lines += [
                f"Verdict: **{'qualifies' if verdict['qualifies'] else 'does not qualify'}** — "
                f"{verdict['reason']}",
                "",
                f"{verdict['compounds_active']} of {verdict['compounds']} in-scope compound(s) at "
                f"or below {verdict['threshold_nM'] / 1000:g} µM under "
                f"`{verdict['policy_version']}` (scope: {verdict['modality_scope']}); "
                f"{verdict['compounds_weak']} above it, {verdict['compounds_unknown']} undecided, "
                f"{verdict['compounds_not_applicable']} not a potency; "
                f"{verdict['measurements']} in-scope record(s), "
                f"{verdict['records_without_structure']} value(s) without a structure.",
                "",
            ]
        else:
            lines += ["Verdict: not computed for this target.", ""]
    lines += [
        "---",
        "",
        "A `failed` row is a source outage; an `empty` row is a source that answered",
        "with nothing; a target absent from this matrix was never investigated. The",
        "three are different facts and are not collapsed here.",
        "",
    ]
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("queries", nargs="*", help="gene symbols or accessions; default the cohort")
    parser.add_argument("--out", default=None, help="write here; '-' for stdout")
    parser.add_argument("--json", action="store_true", help="emit the JSON record, not markdown")
    parser.add_argument(
        "--investigate",
        action="store_true",
        help="resolve and retrieve for each query (writes rows; spends upstream requests)",
    )
    parser.add_argument(
        "--source",
        action="append",
        choices=EXTERNAL_SOURCES,
        help=f"repeatable; default all of {', '.join(EXTERNAL_SOURCES)}",
    )
    parser.add_argument("--yes", action="store_true", help="required with --investigate")
    parser.add_argument(
        "--declarations",
        action="store_true",
        help=(
            "live, read-only: measure how many of each target's kept records carry a "
            "source-declared document reference, and why the rest do not (B-02). Writes "
            "nothing to the database; spends upstream requests."
        ),
    )
    parser.add_argument(
        "--max-activities",
        type=int,
        default=DEFAULT_MAX_ACTIVITIES,
        help="activity records to fetch per ChEMBL target id in --declarations",
    )
    args = parser.parse_args()

    queries = tuple(args.queries) if args.queries else DEFAULT_COHORT
    if args.investigate and not args.yes:
        _log("refusing to write rows and spend upstream requests without --yes.")
        return 2
    if args.investigate and args.declarations:
        _log(
            "refusing --investigate with --declarations: the measurement is read-only, and a "
            "caller must not be left thinking rows were written. Run the investigation first."
        )
        return 2
    sources = tuple(args.source) if args.source else EXTERNAL_SOURCES

    engine = make_engine()
    generated_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
    # The build identity `/healthz` reports, read from the same constant the app
    # serves, so the record names the build it was taken from without a network
    # call (the operator's binary may sit behind a proxy this tool cannot see).
    build = __version__

    if args.declarations:
        _log(f"measuring document-reference coverage for {len(queries)} target(s), live")
        max_activities = max(1, args.max_activities)
        measured = _declarations(engine, queries, max_activities)
        bounds = {
            "max_activities_per_target": max_activities,
            "max_document_lookups": ChEMBLDiscoveryAdapter().max_document_lookups,
        }
        record = {
            "generated_at": generated_at,
            "api_version": build,
            "mode": "declarations",
            "requested_cohort": list(queries),
            "bounds": bounds,
            "targets": measured,
            "totals": _declaration_totals(measured),
        }
        text_out = (
            json.dumps(record, ensure_ascii=False, indent=2)
            if args.json
            else _render_declarations(measured, generated_at, build, bounds)
        )
        _write_or_print(text_out, args.out)
        return 0

    resolution: dict[str, dict] = {}
    if args.investigate:
        _log(f"investigating {len(queries)} target(s) from {', '.join(sources)}")
        resolution = _investigate(engine, queries, sources)
    else:
        resolution_service = targets_svc.TargetResolutionService()
        for query in queries:
            existing = resolution_service.find_target(engine, query)
            resolution[query] = {
                "resolution_status": (
                    f"stored target {existing.target_key}" if existing else "not stored"
                )
            }

    rows, _targets = _build_rows(engine)
    record = {
        "generated_at": generated_at,
        "api_version": build,
        "requested_cohort": list(queries),
        "sources_requested": list(sources) if args.investigate else None,
        "resolution": resolution,
        "rows": rows,
    }
    text_out = (
        json.dumps(record, ensure_ascii=False, indent=2)
        if args.json
        else _render(rows, queries, resolution, generated_at, build)
    )
    _write_or_print(text_out, args.out)

    missing = [
        q
        for q in queries
        if not any(
            q.lower() in ((row.get("target_key") or "").lower(), (row.get("gene_symbol") or "").lower(),
                          (row.get("uniprot_accession") or "").lower())
            for row in rows
        )
    ]
    if missing:
        _log(
            "no stored coverage for: "
            + ", ".join(missing)
            + " — report them as not investigated, never as zero results."
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
