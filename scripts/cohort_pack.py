#!/usr/bin/env python
"""Reproducible review pack for a coverage cohort (B-32, machine half).

`scripts/cohort_coverage.py` answers "what did the sources retrieve". This script
answers the reviewer's question before the cross-read starts: *can this pack be
reproduced, and what exactly does each number come from?* For a named set of
stored targets it emits one JSON record and one Markdown record that carry:

  * the served build identity, fetched verbatim from the stack's `/healthz`
    (B-34) — a mismatch against `--expected-build` fails the run, and an unknown
    or unreachable identity is recorded as such, never passed silently;
  * the schema state (which migrations the database applied, and what the
    generator's checkout still holds unapplied);
  * each target's resolved identity and its per-source retrievals with access
    path, version, status, counts and `retrieved_at`;
  * the potency verdict **twice**: source-only (hand-added rows excluded) and
    combined workspace — the same policy, two stated scopes, so "what the
    retrieved sources support" is never blended with "what this workspace
    supports";
  * per-record stratification hooks for the reviewer (evidence class, censor
    direction, stereochemistry stored, source-declared patent versus corpus
    occurrence, supplement provenance);
  * an explicit limits section: what a machine prepared and what it cannot
    approve.

It records; it judges nothing. It calls no source, writes nothing to the
database, and the pack is not the independent cross-read — a machine can
prepare the pack but cannot approve its own review, and the pack says so.

Usage:

  services/core/.venv/bin/python scripts/cohort_pack.py \
      --json-out benchmarks/cohort-pack-2026-09-16.json \
      --md-out   benchmarks/cohort-pack-2026-09-16.md

  # refuse to record against a build that is not the one you expect
  services/core/.venv/bin/python scripts/cohort_pack.py --expected-build <id>

Exit codes: 0 recorded (identity merely recorded when no expectation is given),
1 served identity unreachable or not the expected one, 2 usage error.
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
# `python scripts/cohort_pack.py` puts the script dir on sys.path itself; a
# by-path import (tests) does not, and the sibling recorder module below is part
# of this script's contract either way.
sys.path.insert(0, str(REPO_ROOT / "services" / "core"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from sqlalchemy import text  # noqa: E402

from build_identity import UNKNOWN, _fetch_health  # noqa: E402

from spago_core import __version__  # noqa: E402
from spago_core.adapters.chembl_discovery import (  # noqa: E402
    DEFAULT_MAX_ACTIVITIES,
    DEFAULT_MAX_MOLECULE_LOOKUPS,
)
from spago_core.adapters.http import DEFAULT_MAX_ATTEMPTS, DEFAULT_TIMEOUT_S  # noqa: E402
from spago_core.adapters.pubchem import DEFAULT_MAX_AIDS  # noqa: E402
from spago_core.chemistry.activities import classify_activity  # noqa: E402
from spago_core.config import get_settings  # noqa: E402
from spago_core.db.engine import make_engine  # noqa: E402
from spago_core.db.migrations import _migration_files  # noqa: E402
from spago_core.domain import USER_SUPPLEMENT_SOURCE  # noqa: E402
from spago_core.services import discovery as discovery_svc  # noqa: E402
from spago_core.services import targets as targets_svc  # noqa: E402
from spago_core.services.reference import (  # noqa: E402
    MAX_VERDICT_MEASUREMENTS,
    SCOPED_MODALITIES,
    policy_from_settings,
    reference_verdicts,
)

#: The acceptance cohort of `docs/online-capability.md` §6, named the way it was
#: investigated. The IL-6/IL-6R gene symbols are stored under their accessions'
#: targets (their symbol forms also match group targets), so the default asks
#: for the accessions — the same choice `benchmarks/cohort-coverage-2026-09-16.md`
#: records — while any query form remains available on the command line.
PACK_COHORT = ("TSLP", "CD40LG", "P05231", "P08887", "EGFR")

#: The limits section, stated in the pack itself rather than implied: the pack is
#: machine preparation, never the review's approval. (B-32's gated half.)
LIMITS = (
    "This pack was prepared by a machine (`scripts/cohort_pack.py`) from stored rows "
    "and served metadata. A machine can prepare a review but cannot approve one: the "
    "independent human cross-read (B-32's gated half, feeding B-31) is not performed "
    "or recorded here, and nothing in this file may be read as its result.",
    "Every number describes this stored workspace only. A different stored workspace "
    "(for example the isolated `*-accept` rehearsal) holds different rows and can "
    "carry a different verdict; that is different data, not a conflicting measurement.",
    "The verdicts were recomputed by the generator checkout (identity below) from the "
    "stack's stored rows through the shipped service functions; the served build "
    "identity is what `/healthz` reported. When the two differ, the pack names both "
    "instead of blending them.",
    "The source-only verdict excludes hand-added rows (`user_supplement`); the "
    "combined verdict includes them. Unconfirmed proposals and withdrawn rows are "
    "outside both counts and stay visible in the combined verdict's own fields.",
    "No source was called and nothing was written: the pack is a read. A licensed "
    "snapshot (B-23) is an operator access path with no leg in this pack, so nothing "
    "here is a snapshot scan of any publication.",
    "Records that carried a value but no drawable structure are counted as retrieval "
    "rejections (`records_without_structure`), never as compounds: a thin set is not "
    "a negative result.",
)


def _log(message: str = "") -> None:
    print(message, file=sys.stderr, flush=True)


def _generator_identity() -> str:
    """The checkout that computed the pack's verdicts, or an explicit unknown.

    The served image reports its own identity through /healthz; this one answers
    for the code that ran the service functions here, which is a different fact
    whenever the generator runs outside the image.
    """
    try:
        described = subprocess.run(
            ["git", "describe", "--always", "--dirty"],
            cwd=REPO_ROOT,
            capture_output=True,
            text=True,
            timeout=10,
            check=True,
        ).stdout.strip()
        return described or UNKNOWN
    except Exception:
        return UNKNOWN


def _build_block(base_url: str, timeout: float, expected: str | None) -> tuple[dict, int]:
    """The served identity verbatim, plus the comparison's answer.

    Returns the block and the exit code the comparison dictates: a mismatch or an
    unreachable server is not a pass (B-34's recorder contract), while an unknown
    with no expectation is recorded, not failed.
    """
    try:
        health = _fetch_health(base_url, timeout)
    except Exception as exc:
        return (
            {
                "fetched_from": base_url + "/healthz",
                "status": "unreachable",
                "error": str(exc),
                "expected_build_id": expected,
                "match": False,
            },
            1,
        )
    served = str(health.get("build_id", "")).strip()
    source = str(health.get("build_source", "")).strip()
    if expected is None:
        match = "not checked"
        code = 0
    elif served == UNKNOWN or source == UNKNOWN:
        match = False
        code = 1
    else:
        match = served == expected
        code = 0 if match else 1
    return (
        {
            "fetched_from": base_url + "/healthz",
            "status": "ok",
            # The payload as served, unedited: a reviewer reads what the stack
            # said, not what this script chose to keep.
            "healthz": dict(health),
            "build_id": served,
            "build_source": source,
            "expected_build_id": expected,
            "match": match,
        },
        code,
    )


def _schema_block(engine, migrations_dir: Path) -> dict:
    """Applied migrations from the database; pending ones from the checkout.

    Read-only: `schema_migrations` is only selected, never created, so a database
    without the table is reported instead of being brought into existence by an
    audit (unlike `applied_versions`, which is an ingestion-time helper). The
    file list comes from the migration runner's own parser, so "pending" means
    exactly what `run_migrations` would apply.
    """
    try:
        files = _migration_files(migrations_dir)
    except (FileNotFoundError, ValueError) as exc:
        return {"status": "unreadable", "error": str(exc), "applied": [], "pending": None}
    try:
        with engine.connect() as conn:
            rows = (
                conn.execute(
                    text(
                        "SELECT version, filename, applied_at FROM schema_migrations "
                        "ORDER BY version"
                    )
                )
                .mappings()
                .all()
            )
    except Exception as exc:
        return {"status": "unreadable", "error": str(exc), "applied": [], "pending": None}
    applied = [
        {
            "version": row["version"],
            "filename": row["filename"],
            "applied_at": (
                row["applied_at"].astimezone(timezone.utc).isoformat(timespec="seconds")
                if isinstance(row["applied_at"], datetime)
                else str(row["applied_at"])
            ),
        }
        for row in rows
    ]
    applied_versions = {row["version"] for row in applied}
    pending = sorted(path.name for version, path in files if version not in applied_versions)
    return {
        "status": "ok",
        "applied": applied,
        "applied_count": len(applied),
        "pending_in_generator_checkout": pending,
    }


def _query_bounds() -> dict:
    """The bounds in force for this pack's reads and for a re-retrieval.

    The adapter defaults are what a fresh investigation would spend today; the
    stored rows were retrieved under the bounds of their own time, which each
    source row's `query` and `warnings` carry. Stating both keeps a re-run from
    being silently compared with an older retrieval.
    """
    return {
        "verdict_read_cap_per_target": MAX_VERDICT_MEASUREMENTS,
        "retrieval_defaults_if_re_investigated": {
            "chembl_max_activities_per_target_id": DEFAULT_MAX_ACTIVITIES,
            "chembl_max_molecule_lookups": DEFAULT_MAX_MOLECULE_LOOKUPS,
            "pubchem_max_assay_ids": DEFAULT_MAX_AIDS,
            "http_max_attempts": DEFAULT_MAX_ATTEMPTS,
            "http_timeout_s": DEFAULT_TIMEOUT_S,
        },
    }


def _target_records(
    engine,
    target_id: uuid.UUID,
    *,
    threshold_nm: float,
    all_modalities: bool,
) -> tuple[list[dict], bool]:
    """The reviewer's stratification frame: every measurement row in this target's
    investigation scope, with the hooks a cross-read samples by.

    The same cap and the same scope the verdict reads, so the frame and the
    counts describe one set; `truncated` is reported rather than hidden. The
    per-record class comes from the verdict's own rule (`classify_activity` under
    the pack's policy), never from a second definition.
    """
    cap = MAX_VERDICT_MEASUREMENTS
    with engine.connect() as conn:
        rows = (
            conn.execute(
                text(
                    """
                    SELECT m.id AS measurement_id, m.source_name,
                           m.standard_type, m.value, m.unit, m.relation,
                           coalesce(m.evidence_class, 'unspecified') AS evidence_class,
                           m.document_patent_number,
                           c.inchikey,
                           (coalesce(c.canonical_smiles, '') <> '') AS smiles_stored,
                           c.has_stereo,
                           coalesce(c.modality, 'unclassified') AS modality,
                           (SELECT count(*) FROM current_compound_mentions cm
                             WHERE cm.compound_id = m.compound_id) AS corpus_occurrences
                    FROM investigation_measurements m
                    JOIN compounds c ON c.id = m.compound_id
                    WHERE m.investigation_target_id = :tid
                    ORDER BY m.id
                    LIMIT :cap
                    """
                ),
                {"tid": target_id, "cap": cap + 1},
            )
            .mappings()
            .all()
        )
    truncated = len(rows) > cap
    out = []
    for row in rows[:cap]:
        activity_class, rule = classify_activity(
            float(row["value"]), row["unit"], row["relation"],
            row["standard_type"], threshold_nm,
        )
        out.append(
            {
                "measurement_id": str(row["measurement_id"]),
                "source_name": row["source_name"],
                "is_supplement": row["source_name"] == USER_SUPPLEMENT_SOURCE,
                "in_scope": bool(all_modalities) or row["modality"] in SCOPED_MODALITIES,
                "modality": row["modality"],
                "evidence_class": row["evidence_class"],
                "relation": row["relation"],
                "standard_type": row["standard_type"],
                "value": float(row["value"]),
                "unit": row["unit"],
                "activity_class": activity_class.value,
                "activity_class_rule": rule,
                "inchikey": row["inchikey"],
                "smiles_stored": bool(row["smiles_stored"]),
                "has_stereo": bool(row["has_stereo"]) if row["has_stereo"] is not None else False,
                "source_declared_patent": row["document_patent_number"],
                "corpus_occurrences": int(row["corpus_occurrences"] or 0),
            }
        )
    return out, truncated


def _source_rows(matrix: list[dict], target_id) -> list[dict]:
    """The stored retrievals for one target, as the shipped matrix read them."""
    rows = []
    for row in matrix:
        if row["target_id"] != target_id:
            continue
        rows.append(
            {
                "access_path": "target-led retrieval (B-02)",
                "source_name": row["source_name"],
                "status": row["status"],
                "query": row["query"],
                "records_seen": row["records_seen"],
                "records_kept": row["records_kept"],
                "records_excluded": row["records_excluded"],
                "rejection_counts": row["rejection_counts"],
                "reference_counts": row["reference_counts"],
                "candidates": row["candidates"],
                "small_molecule_candidates": row["small_molecule_candidates"],
                "dataset_version": row["dataset_version"],
                "source_version": row["source_version"],
                "retrieved_at": row["retrieved_at"],
                "warnings": row["warnings"],
            }
        )
    return sorted(rows, key=lambda row: row["source_name"])


def _verdict_dict(verdict) -> dict:
    return verdict.model_dump(mode="json")


def _counts(records: list[dict], key: str) -> dict:
    out: dict[str, int] = {}
    for record in records:
        value = str(record.get(key) or "unspecified")
        out[value] = out.get(value, 0) + 1
    return dict(sorted(out.items(), key=lambda item: (-item[1], item[0])))


def _stratification(records: list[dict]) -> dict:
    """Counts the reviewer samples by, derived from the record list itself."""
    stereo = [
        r for r in records if r["smiles_stored"] and r["inchikey"]
    ]
    declared = [r for r in records if r["source_declared_patent"]]
    occurring = [r for r in records if r["corpus_occurrences"] > 0]
    return {
        "records": len(records),
        "records_in_policy_scope": sum(1 for r in records if r["in_scope"]),
        "by_evidence_class": _counts(records, "evidence_class"),
        "by_relation": _counts(records, "relation"),
        "by_activity_class": _counts(records, "activity_class"),
        "supplement_records": sum(1 for r in records if r["is_supplement"]),
        "stereochemistry_stored_smiles_and_inchikey": len(stereo),
        "records_with_source_declared_patent": len(declared),
        "source_declared_patents": sorted({r["source_declared_patent"] for r in declared}),
        "records_with_corpus_occurrence": len(occurring),
    }


def _verdict_lines(label: str, verdict: dict) -> list[str]:
    return [
        f"Verdict ({label}): **{'qualifies' if verdict['qualifies'] else 'does not qualify'}**"
        f" — {verdict['reason']}",
        "",
        f"{verdict['compounds_active']} of {verdict['compounds']} in-scope compound(s) at or "
        f"below {verdict['policy']['threshold_label']} under "
        f"`{verdict['policy']['version']}` (scope: {verdict['policy']['modality_scope']}); "
        f"{verdict['compounds_weak']} above it, {verdict['compounds_unknown']} undecided, "
        f"{verdict['compounds_not_applicable']} not a potency; "
        f"{verdict['measurements']} in-scope record(s), "
        f"{verdict['records_without_structure']} value(s) without a structure"
        + (
            f"; {verdict['active_compounds_outside_scope']} active(s) outside the modality scope"
            if verdict["active_compounds_outside_scope"]
            else ""
        )
        + ".",
        "",
    ]


def _render_markdown(record: dict) -> str:
    """The human record. Every number is copied from the JSON record, none computed."""
    build = record["build"]
    schema = record["schema"]
    policy = record["policy"]
    lines = [
        "# Cohort review pack (B-32, machine half)",
        "",
        f"Generated {record['generated_at']} by `scripts/cohort_pack.py` "
        f"(generator checkout `{record['generator']['checkout']}`, spago_core "
        f"`{record['generator']['spago_core_version']}`). Raw record: "
        f"`{record['json_path']}`.",
        "",
        "## Served build",
        "",
    ]
    if build["status"] != "ok":
        lines += [
            f"**Identity not readable** from {build['fetched_from']}: {build.get('error')}. "
            "The pack is recorded with the gap visible; it does not pass silently.",
            "",
        ]
    else:
        expected = build.get("expected_build_id")
        match = build["match"]
        lines += [
            f"Fetched verbatim from `{build['fetched_from']}`:",
            "",
            f"- build_id `{build['build_id']}` (build_source: {build['build_source']})",
            f"- api_version {build['healthz'].get('api_version')} · "
            f"dataset_version {build['healthz'].get('dataset_version')} · "
            f"status {build['healthz'].get('status')}",
            f"- expected: {f'`{expected}`' if expected else 'none given'} · "
            f"match: {match if match == 'not checked' else ('**yes**' if match else '**NO**')}",
            "",
        ]
    if schema["status"] == "ok":
        pending = schema["pending_in_generator_checkout"]
        applied = schema["applied"]
        range_note = (
            f"({applied[0]['filename']} … {applied[-1]['filename']})"
            if applied
            else "(none applied)"
        )
        lines += [
            "## Schema",
            "",
            f"{schema['applied_count']} migration(s) applied {range_note}; "
            f"pending in the generator's checkout: {', '.join(pending) if pending else 'none'}.",
            "",
        ]
    lines += [
        "## Policy and bounds",
        "",
        f"`{policy['version']}`: threshold {policy['threshold_label']}, minimum "
        f"{policy['min_compounds']} compound(s), scope {policy['modality_scope']}. "
        f"Verdict read cap {record['query_bounds']['verdict_read_cap_per_target']} rows per "
        "target. Retrieval defaults if a target were re-investigated: "
        + ", ".join(
            f"{key}={value}"
            for key, value in record["query_bounds"][
                "retrieval_defaults_if_re_investigated"
            ].items()
        )
        + ". Stored rows carry the bounds of their own retrieval time in each "
        "source row's `query` and `warnings`.",
        "",
        "## Targets",
        "",
        f"Requested cohort: {', '.join(record['requested_cohort'])}",
        "",
    ]
    for entry in record["targets"]:
        query = entry["query"]
        lines.append(f"### {query}")
        lines.append("")
        target = entry.get("target")
        if target is None:
            lines += [
                f"**Not stored** — {entry['resolution']}. A target with no stored "
                "retrieval has no coverage to report; this is not a zero result.",
                "",
            ]
            continue
        lines += [
            f"{target['target_key']} — {target['name'] or 'unnamed'} · "
            f"UniProt {target['uniprot_accession'] or '—'} · "
            f"{target['target_type'] or '—'} · {target['organism'] or '—'} "
            f"(resolved via {target['source_name']} {target['dataset_version']})",
            "",
            "| Source | Status | Seen | Kept | Excluded | Candidates | Small-molecule | Version | Retrieved |",
            "| --- | --- | --- | --- | --- | --- | --- | --- | --- |",
        ]
        for row in entry["sources"]:
            lines.append(
                f"| {row['source_name']} | {row['status']} | {row['records_seen']} | "
                f"{row['records_kept']} | {row['records_excluded']} | {row['candidates']} | "
                f"{row['small_molecule_candidates']} | "
                f"{row['dataset_version'] or row['source_version'] or '—'} | "
                f"{row['retrieved_at']} |"
            )
        lines.append("")
        lines += _verdict_lines("source-only", entry["verdict_source_only"])
        lines += _verdict_lines("combined workspace", entry["verdict_combined"])
        strat = entry["stratification"]
        lines += [
            f"Stratification ({strat['records']} record(s) in the read, "
            f"{strat['records_in_policy_scope']} inside the policy scope): "
            f"evidence {json.dumps(strat['by_evidence_class'])}; "
            f"censor relation {json.dumps(strat['by_relation'])}; "
            f"class {json.dumps(strat['by_activity_class'])}; "
            f"{strat['supplement_records']} supplement record(s); "
            f"stereo stored (SMILES + InChIKey) for "
            f"{strat['stereochemistry_stored_smiles_and_inchikey']} of {strat['records']}; "
            f"{strat['records_with_source_declared_patent']} record(s) name a source-declared "
            f"patent ({', '.join(strat['source_declared_patents']) or 'none'}) while "
            f"{strat['records_with_corpus_occurrence']} occur in a stored corpus document — "
            "declared and occurring are counted separately, never merged.",
            "",
        ]
        if entry["records_truncated"]:
            lines += [
                "> The record read hit its cap; the stratification frame is truncated "
                "and says so rather than passing as complete.",
                "",
            ]
    lines += ["## Limits", ""]
    lines += [f"- {limit}" for limit in record["limits"]]
    lines += [""]
    return "\n".join(lines)


def _write(path: str | None, payload: str) -> None:
    if not path:
        return
    if path == "-":
        print(payload)
        return
    with open(path, "w", encoding="utf-8") as handle:
        handle.write(payload if payload.endswith("\n") else payload + "\n")
    _log(f"wrote {path}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("queries", nargs="*", help="gene symbols or accessions; default the cohort")
    parser.add_argument("--json-out", default=None, help="write the JSON record here; '-' for stdout")
    parser.add_argument("--md-out", default=None, help="write the Markdown record here; '-' for stdout")
    parser.add_argument(
        "--base-url",
        default=None,
        help="the stack whose /healthz names the served build; defaults to $SPAGO_BASE_URL",
    )
    parser.add_argument(
        "--expected-build",
        default=None,
        help="fail (exit 1) unless the served build_id equals this",
    )
    parser.add_argument("--timeout", type=float, default=10.0, help="/healthz timeout in seconds")
    parser.add_argument(
        "--database-url", default=None, help="defaults to $SPAGO_DATABASE_URL or the deployment default"
    )
    parser.add_argument(
        "--compact",
        action="store_true",
        help=(
            "omit the per-record rows and keep the aggregate blocks (verdicts, "
            "stratification, sources); the stratification counts are computed "
            "from the full records either way. For committed summary artifacts — "
            "the full reviewer pack is one command away without it."
        ),
    )
    args = parser.parse_args(argv)

    if args.expected_build == UNKNOWN:
        _log("usage error: --expected-build unknown is not an expectation; omit it to record one.")
        return 2
    if not args.json_out and not args.md_out:
        _log("usage error: give --json-out and/or --md-out ('-' for stdout).")
        return 2

    base_url = args.base_url or os.environ.get("SPAGO_BASE_URL") or "http://127.0.0.1:8000"
    queries = tuple(args.queries) if args.queries else PACK_COHORT

    build, code = _build_block(base_url, args.timeout, args.expected_build)
    if build["status"] != "ok":
        _log(f"FAILED: cannot read the served build identity from {base_url}/healthz")
    elif args.expected_build is not None and build["match"] is not True:
        _log(f"MISMATCH: expected build_id={args.expected_build}, served {build['build_id']}")

    settings = get_settings()
    engine = make_engine(args.database_url or settings.database_url)
    policy = policy_from_settings(settings)

    schema = _schema_block(engine, settings.migrations_dir)
    matrix = discovery_svc.coverage_matrix(engine)
    resolution = targets_svc.TargetResolutionService()

    targets: list[dict] = []
    for query in queries:
        found = resolution.find_target(engine, query)
        if found is None:
            targets.append(
                {
                    "query": query,
                    "resolution": "no stored target matches the query",
                    "target": None,
                    "sources": [],
                    "verdict_source_only": None,
                    "verdict_combined": None,
                    "stratification": None,
                    "records_truncated": False,
                }
            )
            _log(f"  {query:10s} not stored — reported as not investigated, not as zero")
            continue
        verdicts = reference_verdicts(
            engine, [found], policy, include_supplements=False
        )
        combined = reference_verdicts(engine, [found], policy, include_supplements=True)
        records, truncated = _target_records(
            engine,
            found.id,
            threshold_nm=policy.threshold_nm,
            all_modalities=policy.all_modalities,
        )
        targets.append(
            {
                "query": query,
                "resolution": f"stored target {found.target_key}",
                "target": {
                    "target_key": found.target_key,
                    "name": found.name,
                    "gene_symbol": found.gene_symbol,
                    "uniprot_accession": found.uniprot_accession,
                    "target_type": found.target_type,
                    "organism": found.organism,
                    "source_name": found.source_name,
                    "dataset_version": found.dataset_version,
                },
                "sources": _source_rows(matrix, found.id),
                "verdict_source_only": _verdict_dict(verdicts[found.id]),
                "verdict_combined": _verdict_dict(combined[found.id]),
                "stratification": _stratification(records),
                "records": None if args.compact else records,
                "records_truncated": truncated,
                **(
                    {"records_note": "omitted by --compact; regenerate without it for the full reviewer pack"}
                    if args.compact
                    else {}
                ),
            }
        )
        source_only = verdicts[found.id]
        combined_only = combined[found.id]
        _log(
            f"  {query:10s} source-only {source_only.compounds_active}/"
            f"{source_only.compounds} · combined {combined_only.compounds_active}/"
            f"{combined_only.compounds}"
        )

    record = {
        "kind": "cohort-pack",
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "generator": {
            "script": "scripts/cohort_pack.py",
            "checkout": _generator_identity(),
            "spago_core_version": __version__,
        },
        "json_path": args.json_out if args.json_out not in (None, "-") else "(stdout)",
        "requested_cohort": list(queries),
        "build": build,
        "schema": schema,
        "policy": policy.model_dump(mode="json"),
        "query_bounds": _query_bounds(),
        "targets": targets,
        "limits": list(LIMITS),
    }

    if args.json_out:
        _write(args.json_out, json.dumps(record, ensure_ascii=False, indent=2))
    if args.md_out:
        _write(args.md_out, _render_markdown(record))
    return code


if __name__ == "__main__":
    raise SystemExit(main())
