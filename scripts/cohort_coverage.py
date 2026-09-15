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
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone

from spago_core import __version__
from spago_core.config import get_settings
from spago_core.db.engine import make_engine
from spago_core.services import discovery as discovery_svc
from spago_core.services import targets as targets_svc
from spago_core.services.discovery import EXTERNAL_SOURCES
from spago_core.services.reference import policy_from_settings, reference_verdicts

#: The acceptance cohort named in `docs/online-capability.md` §6, plus the EGFR
#: positive control from `benchmarks/online00-coverage-2026-09-15.md` — a control
#: that must return a large set, so an empty acceptance target cannot be mistaken
#: for a broken adapter.
DEFAULT_COHORT = ("TSLP", "CD40LG", "IL-6", "IL-6R", "EGFR")


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
    args = parser.parse_args()

    queries = tuple(args.queries) if args.queries else DEFAULT_COHORT
    if args.investigate and not args.yes:
        _log("refusing to write rows and spend upstream requests without --yes.")
        return 2
    sources = tuple(args.source) if args.source else EXTERNAL_SOURCES

    engine = make_engine()
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
    generated_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
    # The build identity `/healthz` reports, read from the same constant the app
    # serves, so the record names the build it was taken from without a network
    # call (the operator's binary may sit behind a proxy this tool cannot see).
    build = __version__

    record = {
        "generated_at": generated_at,
        "api_version": build,
        "requested_cohort": list(queries),
        "sources_requested": list(sources) if args.investigate else None,
        "resolution": resolution,
        "rows": rows,
    }
    text = (
        json.dumps(record, ensure_ascii=False, indent=2)
        if args.json
        else _render(rows, queries, resolution, generated_at, build)
    )

    if args.out == "-" or args.out is None:
        print(text)
    else:
        with open(args.out, "w", encoding="utf-8") as handle:
            handle.write(text if text.endswith("\n") else text + "\n")
        _log(f"wrote {args.out}")

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
