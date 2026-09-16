#!/usr/bin/env python
"""Load a list of patents into the corpus, one package at a time (B-01).

The single-patent path is `extract_surechembl.py` (extract one family scope) plus
`python -m spago_core.import_package` (ingest it). Scaling that to a target list —
the shape real work arrives in, a screening set or a competitor's portfolio —
should not need a hand-written loop per session, and it must not report success
for a corpus that is missing half the list.

This script is that loop, and nothing more:

    services/core/.venv/bin/python scripts/corpus_batch.py \
        --patents my-patents.txt --release 2026-09-08 --workdir var/batch-2026-09-16

It chunks the list, extracts a package per chunk, imports it, and keeps a
resumable state file (`STATE.json` in the workdir) so an interrupted run
continues where it stopped instead of re-downloading. It fails loudly: the exit
code is non-zero if any publication is not in the corpus when the run ends, and
the missing numbers are printed as a list, not summarized as a percentage.

Honesty rules this script follows (AGENTS.md §34, §22):
  * a chunk is `completed` only after its import job says `completed` against the
    database — a package written to disk is not chemistry in the corpus;
  * at the end the *database* is asked which requested numbers it holds
    (`spago_core.corpus_status` asks the same question); the answer, not the loop,
    decides the exit code;
  * a publication the release does not contain is reported as `not in release`,
    not as a patent without chemistry;
  * `--fail-fast` stops at the first bad chunk; the default continues and reports
    everything that failed, because a partial corpus is more useful than none and
    the missing list is the deliverable of a failed run.

Usage details:
  --patents FILE     one publication number per line; `#` comments and blank lines
                     are ignored. A CSV/TSV export works too with --column.
  --column NAME|N    column to read when the file has more than one field.
  --per-package N    publications per extraction package (default 20). Larger
                     packages amortize the release scan; smaller ones isolate a
                     failure to fewer patents.
  --retry-failed     re-run chunks that failed in an earlier attempt (completed
                     chunks are always skipped, which is what makes a re-run cheap).
  --dry-run          print the plan (chunks, counts, output paths) and stop.
"""
from __future__ import annotations

import argparse
import json
import logging
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
EXTRACTOR = REPO_ROOT / "scripts" / "extract_surechembl.py"
CORE_DIR = REPO_ROOT / "services" / "core"

# The corpus is read in-process (the same code the API and the terminal surface
# use), so this script must run under the core interpreter. Say that plainly
# instead of failing later on a confusing import error.
if str(CORE_DIR) not in sys.path:
    sys.path.insert(0, str(CORE_DIR))
try:
    from spago_core.db import make_engine
    from spago_core.services.core import publications_in_corpus, read_publication_list
except ImportError:  # pragma: no cover - operator-facing guard
    raise SystemExit(
        "corpus_batch.py must run with the SPAgo core interpreter:\n"
        f"  {CORE_DIR / '.venv' / 'bin' / 'python'} scripts/corpus_batch.py …"
    )

logger = logging.getLogger("corpus_batch")


def chunk(items: list[str], size: int) -> list[list[str]]:
    return [items[i : i + size] for i in range(0, len(items), size)]


def load_state(path: Path) -> dict:
    if path.is_file():
        return json.loads(path.read_text(encoding="utf-8"))
    return {"created_at": None, "chunks": {}}


def save_state(path: Path, state: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(state, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    tmp.replace(path)


def run_extract(
    patents: list[str], out_dir: Path, release: str, compounds: Path | None
) -> tuple[int, str]:
    cmd = [sys.executable, str(EXTRACTOR), "--release", release, "--out", str(out_dir)]
    for number in patents:
        cmd += ["--patent", number]
    if compounds is not None:
        cmd += ["--compounds", str(compounds)]
    proc = subprocess.run(cmd, capture_output=True, text=True, cwd=str(REPO_ROOT))
    return proc.returncode, (proc.stdout + proc.stderr).strip()


def run_import(package_dir: Path) -> tuple[int, str]:
    cmd = [sys.executable, "-m", "spago_core.import_package", str(package_dir)]
    proc = subprocess.run(cmd, capture_output=True, text=True, cwd=str(REPO_ROOT))
    return proc.returncode, (proc.stdout + proc.stderr).strip()


def corpus_check(requested: list[str]) -> tuple[list[str], str | None]:
    """The requested numbers the database does not hold, and why it could not be
    asked. The answer decides the run's exit code, so it is never assumed."""
    try:
        engine = make_engine()
        try:
            present = publications_in_corpus(engine, requested)
        finally:
            engine.dispose()
    except Exception as exc:  # noqa: BLE001 - an unreachable DB is reported, not raised
        return [], f"{type(exc).__name__}: {exc}"
    return [number for number in requested if number not in present], None


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--patents", type=Path, required=True, help="list/CSV file of publication numbers")
    parser.add_argument("--column", default=None, help="column name or index when the file is tabular")
    parser.add_argument("--release", required=True, help="SureChEMBL release directory (YYYY-MM-DD)")
    parser.add_argument("--workdir", type=Path, required=True, help="packages, logs and STATE.json")
    parser.add_argument("--per-package", type=int, default=20, help="publications per package (default 20)")
    parser.add_argument("--compounds", type=Path, default=None, help="pre-downloaded compounds.parquet")
    parser.add_argument("--dry-run", action="store_true", help="print the plan and stop")
    parser.add_argument("--retry-failed", action="store_true", help="re-run chunks that failed earlier")
    parser.add_argument("--fail-fast", action="store_true", help="stop at the first failed chunk")
    args = parser.parse_args(argv)

    if args.per_package < 1:
        parser.error("--per-package must be at least 1")
    if not args.patents.is_file():
        logger.error("patent list not found: %s", args.patents)
        return 2
    if not EXTRACTOR.is_file():
        logger.error("extractor not found: %s", EXTRACTOR)
        return 2

    try:
        requested = read_publication_list(args.patents, args.column)
    except ValueError as exc:
        logger.error("%s", exc)
        return 2
    if not requested:
        logger.error("no publication numbers in %s", args.patents)
        return 2

    workdir: Path = args.workdir
    state_path = workdir / "STATE.json"
    state = load_state(state_path)
    if state["created_at"] is None:
        state["created_at"] = datetime.now(timezone.utc).isoformat()
        state["patents_file"] = str(args.patents)
        state["release"] = args.release
        state["per_package"] = args.per_package

    plan = chunk(requested, args.per_package)
    logger.info(
        "%s publication(s) → %s package(s) of at most %s, workdir %s",
        len(requested), len(plan), args.per_package, workdir,
    )
    if args.dry_run:
        for i, group in enumerate(plan, start=1):
            logger.info("  chunk %02d: %s → %s", i, ", ".join(group), workdir / f"chunk-{i:02d}")
        logger.info("dry run: nothing extracted or imported")
        return 0

    workdir.mkdir(parents=True, exist_ok=True)
    log_path = workdir / "batch.log"

    for i, group in enumerate(plan, start=1):
        key = f"chunk-{i:02d}"
        recorded = state["chunks"].get(key, {})
        if recorded.get("status") == "completed":
            logger.info("[%s] already completed, skipped", key)
            continue
        if recorded.get("status") == "failed" and not args.retry_failed:
            logger.error("[%s] failed in an earlier attempt; --retry-failed re-runs it", key)
            continue

        package_dir = workdir / key
        logger.info("[%s] extracting %s publication(s): %s", key, len(group), ", ".join(group))
        code, output = run_extract(group, package_dir, args.release, args.compounds)
        entry = {
            "patents": group,
            "package": str(package_dir),
            "attempts": int(recorded.get("attempts", 0)) + 1,
            "updated_at": datetime.now(timezone.utc).isoformat(),
        }
        if code != 0:
            entry["status"] = "failed"
            entry["stage"] = "extract"
            entry["error"] = output[-2000:] or f"extractor exited {code}"
            state["chunks"][key] = entry
            save_state(state_path, state)
            logger.error("[%s] extraction failed:\n%s", key, entry["error"])
            with log_path.open("a", encoding="utf-8") as fh:
                fh.write(f"=== {key} extract failed ===\n{output}\n")
            if args.fail_fast:
                break
            continue

        logger.info("[%s] package written; importing", key)
        code, output = run_import(package_dir)
        if code != 0:
            entry["status"] = "failed"
            entry["stage"] = "import"
            entry["error"] = output[-2000:] or f"import exited {code}"
            state["chunks"][key] = entry
            save_state(state_path, state)
            logger.error("[%s] import failed:\n%s", key, entry["error"])
            with log_path.open("a", encoding="utf-8") as fh:
                fh.write(f"=== {key} import failed ===\n{output}\n")
            if args.fail_fast:
                break
            continue

        entry["status"] = "completed"
        entry["finished_at"] = datetime.now(timezone.utc).isoformat()
        entry["import_output"] = output[-2000:]
        state["chunks"][key] = entry
        save_state(state_path, state)
        logger.info("[%s] imported", key)
        with log_path.open("a", encoding="utf-8") as fh:
            fh.write(f"=== {key} imported ===\n{output}\n")

    missing, check_problem = corpus_check(requested)
    unfinished = [
        f"chunk-{i:02d}"
        for i in range(1, len(plan) + 1)
        if state["chunks"].get(f"chunk-{i:02d}", {}).get("status") != "completed"
    ]
    state["missing"] = missing
    state["unfinished_chunks"] = unfinished
    state["coverage_checked_at"] = datetime.now(timezone.utc).isoformat()
    save_state(state_path, state)

    logger.info("%s/%s chunk(s) completed", len(plan) - len(unfinished), len(plan))
    if check_problem:
        logger.error("could not verify the corpus after the run: %s", check_problem)
        logger.error("state written to %s", state_path)
        return 1
    logger.info(
        "%s/%s requested publication(s) are loaded as documents",
        len(requested) - len(missing), len(requested),
    )
    if missing:
        logger.error("NOT in the corpus (%s): %s", len(missing), ", ".join(missing))
    if unfinished:
        # A failed import may have written documents before it stopped, so the
        # document check above can pass while the chemistry is incomplete. The
        # job status, not that check, is what says a chunk landed (AGENTS.md §22).
        logger.error(
            "chunk(s) did not complete — their chemistry is not verified: %s",
            ", ".join(unfinished),
        )
        logger.error("re-run with --retry-failed; detail is in %s", log_path)
    if missing or unfinished:
        logger.error("state written to %s", state_path)
        return 1
    logger.info("state written to %s", state_path)
    return 0


if __name__ == "__main__":
    sys.exit(main())
