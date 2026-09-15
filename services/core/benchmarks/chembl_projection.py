"""ChEMBL activity projection cost, measured on the live API.

ONLINE-08 / AGENTS §20: the adapter requests a field subset
(`ChEMBLDiscoveryAdapter.ACTIVITY_FIELDS`) instead of the full activity record.
That change is only honest if the saving is measured and reproducible, so this
harness measures both variants of the *same* request and reports bytes, record
count and latency per page.

What it measures, and what it does not:

* it replays the shipped request parameters (imported from the adapter, so the
  projected variant cannot drift from the product) against the live endpoint;
* the "full" variant is the counterfactual — the same request without `only=`,
  which is what the adapter sent before the projection was adopted;
* it measures **transfer**, not application latency: the numbers are single
  upstream requests including network distance from wherever this runs. Whether
  the smaller response also arrives sooner is a separate question, and the
  interleaved samples below are the only evidence this record can offer for it.

Run (operator tooling; no database, no writes, a bounded number of requests):

    python -m benchmarks.chembl_projection --target-chembl-id CHEMBL203 \
        --pages 2 --repeat 2 --out /tmp/projection.json
"""
from __future__ import annotations

import argparse
import json
import statistics
import sys
import time
from datetime import datetime, timezone

import httpx

from spago_core.adapters.chembl_discovery import ACTIVITY_FIELDS, PAGE_LIMIT

CHEMBL_BASE_URL = "https://www.ebi.ac.uk"
#: The target the projection was verified against: TSLP's single activity set,
#: small enough that one page covers it (the pair the adapter test cites).
DEFAULT_TARGETS = ("CHEMBL3712931",)


def _one_page(
    client: httpx.Client,
    *,
    target_chembl_id: str,
    offset: int,
    projected: bool,
) -> dict:
    params: dict[str, object] = {
        "target_chembl_id": target_chembl_id,
        "limit": PAGE_LIMIT,
        "offset": offset,
    }
    if projected:
        params["only"] = ACTIVITY_FIELDS
    started = time.monotonic()
    response = client.get("/chembl/api/data/activity.json", params=params)
    latency_ms = int((time.monotonic() - started) * 1000)
    response.raise_for_status()
    payload = response.json()
    activities = payload.get("activities") or []
    keys = sorted({k for a in activities for k in a})
    return {
        "target_chembl_id": target_chembl_id,
        "variant": "projected" if projected else "full",
        "offset": offset,
        "status": response.status_code,
        "bytes": len(response.content),
        "records": len(activities),
        "keys_per_record": len(keys),
        "latency_ms": latency_ms,
    }


def _measure_target(client: httpx.Client, target: str, pages: int, repeat: int) -> list[dict]:
    """Interleaved full/projected requests for one target, page by page."""
    rows: list[dict] = []
    for page in range(pages):
        offset = page * PAGE_LIMIT
        for _ in range(repeat):
            for projected in (False, True):
                row = _one_page(
                    client, target_chembl_id=target, offset=offset, projected=projected
                )
                rows.append(row)
                print(
                    f"  {target} page {page} {row['variant']:9s} "
                    f"{row['bytes']:>9,} bytes {row['records']:>4} records "
                    f"{row['keys_per_record']:>3} keys {row['latency_ms']:>5} ms",
                    file=sys.stderr,
                    flush=True,
                )
                # Keep the upstream cost of the measurement itself modest.
                time.sleep(1.0)
        # A page past the end of the result set is an end-of-data marker, not a
        # payload: the byte statistics must not average it in.
        if all(r["records"] == 0 for r in rows if r["offset"] == offset):
            print(f"  {target} page {page}: past the end of the result set, stopping", file=sys.stderr)
            break
    return rows


def _summarize(rows: list[dict]) -> dict:
    payload = [r for r in rows if r["records"]]
    if not payload:
        return {"measured": False, "reason": "no activity records returned"}
    summary: dict = {"measured": True, "end_of_data_requests": len(rows) - len(payload)}
    for variant in ("full", "projected"):
        variant_rows = [r for r in payload if r["variant"] == variant]
        if not variant_rows:
            continue
        byte_values = [r["bytes"] for r in variant_rows]
        latencies = [r["latency_ms"] for r in variant_rows]
        summary[variant] = {
            "requests": len(variant_rows),
            # Per-page bytes are reported per request: a target whose activity
            # set is smaller than the page returns one page with fewer records,
            # so a "bytes per page" mean would describe the page size, not the
            # response.
            "bytes_median": int(statistics.median(byte_values)),
            "bytes_min": min(byte_values),
            "bytes_max": max(byte_values),
            "records_median": int(statistics.median([r["records"] for r in variant_rows])),
            "keys_per_record": variant_rows[0]["keys_per_record"],
            "latency_ms_median": int(statistics.median(latencies)),
            "latency_ms_min": min(latencies),
            "latency_ms_max": max(latencies),
        }
    if "full" in summary and "projected" in summary:
        full, projected = summary["full"], summary["projected"]
        same_records = full["records_median"] == projected["records_median"]
        summary["saving"] = {
            # Only meaningful when both variants returned the same records; the
            # harness asserts that rather than trusting it.
            "comparable": same_records,
            "bytes_median_delta": full["bytes_median"] - projected["bytes_median"],
            "bytes_percent": round(
                100.0
                * (full["bytes_median"] - projected["bytes_median"])
                / full["bytes_median"],
                1,
            ),
            "keys_per_record_removed": full["keys_per_record"] - projected["keys_per_record"],
            "latency_ms_median_delta": full["latency_ms_median"] - projected["latency_ms_median"],
        }
    return summary


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--target-chembl-id",
        action="append",
        default=None,
        help=f"repeatable; default {DEFAULT_TARGETS[0]}",
    )
    parser.add_argument("--pages", type=int, default=1, help="pages per target")
    parser.add_argument("--repeat", type=int, default=1, help="interleaved samples per page")
    parser.add_argument("--limit", type=int, default=PAGE_LIMIT, help="must match the adapter")
    parser.add_argument("--out", default=None, help="write the JSON record here")
    args = parser.parse_args()
    targets = tuple(args.target_chembl_id or DEFAULT_TARGETS)
    if args.limit != PAGE_LIMIT:
        print(
            f"warning: the adapter sends limit={PAGE_LIMIT}, measuring limit={args.limit}",
            file=sys.stderr,
        )

    per_target: dict[str, list[dict]] = {}
    with httpx.Client(base_url=CHEMBL_BASE_URL, timeout=45.0) as client:
        for target in targets:
            per_target[target] = _measure_target(client, target, args.pages, args.repeat)

    record = {
        "recorded_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "endpoint": CHEMBL_BASE_URL + "/chembl/api/data/activity.json",
        "limit": args.limit,
        "only": ACTIVITY_FIELDS,
        "targets": {
            target: {
                "measurements": rows,
                "summary": _summarize(rows),
            }
            for target, rows in per_target.items()
        },
    }
    if all(not entry["summary"].get("measured") for entry in record["targets"].values()):
        print("no target returned activities; nothing measured", file=sys.stderr)
        if not args.out:
            json.dump(record, sys.stdout, ensure_ascii=False, indent=2)
        return 2

    if args.out:
        with open(args.out, "w", encoding="utf-8") as fh:
            json.dump(record, fh, ensure_ascii=False, indent=2)
        print(f"\nwrote {args.out}", file=sys.stderr)
    else:
        json.dump(record, sys.stdout, ensure_ascii=False, indent=2)
        sys.stdout.write("\n")
    for target, entry in record["targets"].items():
        summary = entry["summary"]
        if not summary.get("measured") or "saving" not in summary:
            print(f"{target}: {summary.get('reason', 'not comparable')}", file=sys.stderr)
            continue
        saving = summary["saving"]
        print(
            f"{target}: {summary['full']['bytes_median']:,} → "
            f"{summary['projected']['bytes_median']:,} bytes "
            f"({saving['bytes_percent']:+.1f}%), "
            f"{summary['full']['keys_per_record']} → {summary['projected']['keys_per_record']} keys, "
            f"median latency {summary['full']['latency_ms_median']} → "
            f"{summary['projected']['latency_ms_median']} ms",
            file=sys.stderr,
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
