"""SPAgo M0 benchmark harness.

Measures the baseline latencies and payload sizes that later milestones must not
regress (PROMPT.md §17). Runs against a live API + seeded PostgreSQL.

Usage:
    python benchmarks/run_benchmarks.py --base-url http://localhost:8000 \
        --output benchmarks/results/m0-baseline.json

The synthetic fixture dataset is tiny; numbers establish regression tracking,
not production capacity claims.
"""
from __future__ import annotations

import argparse
import json
import statistics
import time
from datetime import datetime, timezone
from pathlib import Path

import httpx

N_LOOKUPS = 50
N_LIST_CALLS = 50
N_DEPICTIONS = 20
N_SUMMARY_CALLS = 20
N_PLAN_CALLS = 20


def timed(fn, n: int) -> dict:
    """Run fn n times; report ms statistics."""
    samples = []
    errors = 0
    for _ in range(n):
        start = time.perf_counter()
        try:
            fn()
        except Exception:
            errors += 1
        samples.append((time.perf_counter() - start) * 1000)
    return {
        "runs": n,
        "errors": errors,
        "p50_ms": round(statistics.median(samples), 2),
        "p95_ms": round(sorted(samples)[int(0.95 * (len(samples) - 1))], 2),
        "mean_ms": round(statistics.mean(samples), 2),
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-url", default="http://localhost:8000")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    client = httpx.Client(base_url=args.base_url, timeout=30.0)
    results: dict = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "base_url": args.base_url,
        "dataset": "demo-fixture-v1 (synthetic; scale is not representative of bulk data)",
        "benchmarks": {},
    }

    # --- health / startup state -------------------------------------------------
    res = client.get("/healthz")
    res.raise_for_status()
    results["health"] = res.json()
    assert results["health"]["status"] == "ok", "health check failed; fix before benchmarking"

    # --- patent lookup ------------------------------------------------------------
    results["benchmarks"]["patent_lookup"] = timed(
        lambda: client.get("/api/v1/patents/DEMO-PATENT-A").raise_for_status(), N_LOOKUPS
    )

    # --- compounds table query (family scope) -------------------------------------
    family_id = client.get("/api/v1/patents/DEMO-PATENT-A").json()["family"]["id"]
    results["benchmarks"]["family_compounds_page"] = timed(
        lambda: client.get(f"/api/v1/families/{family_id}/compounds").raise_for_status(),
        N_LIST_CALLS,
    )

    # --- payload sizes --------------------------------------------------------------
    page = client.get(f"/api/v1/families/{family_id}/compounds").json()
    results["payload_bytes"] = {
        "compounds_page_default_100": len(json.dumps(page)),
        "depiction_svg_280x160": len(client.get(f"/api/v1/compounds/{page['items'][0]['compound']['id']}/depiction").content),
        "evidence_list": len(json.dumps(client.get(f"/api/v1/compounds/{page['items'][0]['compound']['id']}/evidence").json())),
    }

    # --- depiction latency (server-side RDKit + disk cache) -------------------------
    compound_ids = [item["compound"]["id"] for item in page["items"]]
    first = compound_ids[0]

    # cold: a size nobody has requested yet forces RDKit generation
    cold_start = time.perf_counter()
    client.get(f"/api/v1/compounds/{first}/depiction", params={"w": 401, "h": 201}).raise_for_status()
    results["benchmarks"]["depiction_cold_single_ms"] = round((time.perf_counter() - cold_start) * 1000, 2)

    results["benchmarks"]["depiction_warm"] = timed(
        lambda: client.get(f"/api/v1/compounds/{first}/depiction").raise_for_status(), N_DEPICTIONS
    )

    # --- evidence fetch ------------------------------------------------------------
    results["benchmarks"]["evidence_fetch"] = timed(
        lambda: client.get(f"/api/v1/compounds/{first}/evidence").raise_for_status(), N_LIST_CALLS
    )

    # --- bulk (DuckDB over Parquet) ---------------------------------------------------
    results["benchmarks"]["bulk_compound_counts"] = timed(
        lambda: client.get("/api/v1/bulk/compound-counts").raise_for_status(), 10
    )

    # --- document-scoped query ---------------------------------------------------------
    doc_id = client.get("/api/v1/patents/DEMO-PATENT-A").json()["document"]["id"]
    results["benchmarks"]["document_scoped_compounds"] = timed(
        lambda: client.get(
            f"/api/v1/families/{family_id}/compounds", params={"document_id": doc_id}
        ).raise_for_status(),
        N_LIST_CALLS,
    )

    # --- ONLINE-01: scoped summaries (offline extractive) -----------------------------
    results["benchmarks"]["summary_family_offline"] = timed(
        lambda: client.post(
            f"/api/v1/families/{family_id}/summary", json={"mode": "offline"}
        ).raise_for_status(),
        N_SUMMARY_CALLS,
    )
    results["benchmarks"]["summary_document_offline"] = timed(
        lambda: client.post(
            f"/api/v1/documents/{doc_id}/summary", json={"mode": "offline"}
        ).raise_for_status(),
        N_SUMMARY_CALLS,
    )
    summary_payload = client.post(
        f"/api/v1/families/{family_id}/summary", json={"mode": "offline"}
    ).json()
    results["payload_bytes"]["summary_response"] = len(json.dumps(summary_payload))

    # --- ONLINE-02: planning (deterministic, no model) --------------------------------
    results["benchmarks"]["plan_identifier"] = timed(
        lambda: client.post(
            "/api/v1/ai/plan", json={"query": "DEMO-PATENT-A"}
        ).raise_for_status(),
        N_PLAN_CALLS,
    )
    plan = client.post("/api/v1/ai/plan", json={"query": "DEMO-PATENT-A"}).json()
    results["payload_bytes"]["plan_response"] = len(json.dumps(plan))
    # Execution is benchmarked through a step that is valid for this dataset. The
    # demo fixture uses synthetic identifiers ("DEMO-PATENT-A") that are
    # deliberately NOT publication-number shaped, so `open_patent` is exercised by
    # the test suite against a realistic number instead of being forced here.
    results["benchmarks"]["plan_execute"] = timed(
        lambda: client.post(
            "/api/v1/ai/plan/execute",
            json={
                "plan": {
                    "query": "summarize the demo family",
                    "producer": "offline",
                    "steps": [{"op": "summarize_family", "family_id": family_id}],
                }
            },
        ).raise_for_status(),
        10,
    )
    results["open_patent_note"] = (
        "The demo fixture's synthetic publication ids are not acceptable to the plan validator by "
        "design; `open_patent` execution timing therefore comes from the benchmark below using the "
        "fixture's own id through the patent route, not from a plan step."
    )
    results["benchmarks"]["patent_lookup_via_plan_equivalent"] = timed(
        lambda: client.get("/api/v1/patents/DEMO-PATENT-A").raise_for_status(), 10
    )

    # --- ONLINE-00: target investigation reads (no external calls) ---------------------
    targets = client.get("/api/v1/targets").json()
    if targets:
        target_id = targets[0]["id"]
        results["benchmarks"]["target_candidates_page"] = timed(
            lambda: client.get(
                f"/api/v1/targets/{target_id}/candidates", params={"limit": 100}
            ).raise_for_status(),
            N_LIST_CALLS,
        )
        results["benchmarks"]["target_coverage"] = timed(
            lambda: client.get(f"/api/v1/targets/{target_id}/coverage").raise_for_status(),
            N_LIST_CALLS,
        )
        results["benchmarks"]["target_measurements"] = timed(
            lambda: client.get(
                f"/api/v1/targets/{target_id}/measurements", params={"limit": 200}
            ).raise_for_status(),
            N_LIST_CALLS,
        )
        results["benchmarks"]["summary_target_offline"] = timed(
            lambda: client.post(
                f"/api/v1/targets/{target_id}/summary", json={"mode": "offline"}
            ).raise_for_status(),
            N_SUMMARY_CALLS,
        )
        candidates = client.get(
            f"/api/v1/targets/{target_id}/candidates", params={"limit": 100}
        ).json()
        results["payload_bytes"]["target_candidates_page_100"] = len(json.dumps(candidates))
        results["target_notes"] = (
            "Target reads are served from the stored investigation; they issue no external request. "
            "Live source retrieval latency is recorded per source in the coverage matrix "
            "(benchmarks/online00-coverage-*.json) and is excluded here."
        )
    else:
        results["target_notes"] = (
            "No resolved target exists in this database, so target read benchmarks were skipped. "
            "Resolve a target first (POST /api/v1/targets/resolve) to include them."
        )

    # --- ONLINE-03: authenticated request overhead --------------------------------------
    if client.get("/api/v1/auth/status").json().get("mode") == "required":
        results["benchmarks"]["projects_list_authenticated"] = timed(
            lambda: client.get("/api/v1/projects").raise_for_status(), N_LIST_CALLS
        )
        results["benchmarks"]["usage_report"] = timed(
            lambda: client.get("/api/v1/usage").raise_for_status(), N_LIST_CALLS
        )
    results["notes"] = [
        "Fixture scale: these numbers track regressions, they are not hosted SLOs.",
        "LLM planning/summary latency and token usage require a configured provider and are "
        "recorded separately by the operator for the chosen host/model.",
    ]

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(results, indent=2) + "\n")
    print(json.dumps(results, indent=2))


if __name__ == "__main__":
    main()
