#!/usr/bin/env python
"""Check that the server being recorded is the build you think it is (B-34).

`/healthz` reports `api_version`, but many builds share one package version.
Since B-34 it also reports the packaging-time identity (`build_id`, and
`build_source` saying where it came from). This script is the recorder's half
of the contract: it reads the served identity, compares it with the one the
run is recorded against, and reports a mismatch or an unknown rather than
passing it — an unchecked "unknown" is exactly the indistinguishable build
B-34 exists to prevent.

What each mode does:

  * no `--expected`, no `--require`: print what this server is, for the run
    record. Exits 0 (recording an observed identity is not a failure).
  * `--expected <id>`: exit 1 unless the served `build_id` equals `<id>`.
    A served "unknown" never equals a real expectation, so it fails too.
  * `--require`: exit 1 when the served identity is unknown, even with no
    expectation — for acceptance runs that must be attributable to a build.

The expectation comes from `--expected` or the environment (`SPAGO_BUILD_ID`,
the same variable `scripts/build_app.sh` exports when it builds). Expecting
"unknown" is a usage error: an expectation is a real identity, and the way to
reject an unknown build is `--require`, not a match against the placeholder.

Alongside the identity, the same payload's `api_version`, `dataset_version`
and `status` are printed, so a run record copied from this output carries its
schema/data context with it.

Exit codes: 0 identity as expected (or merely recorded), 1 mismatch, unknown
where required, or /healthz not readable as an identity — an unreachable
server is not a pass — and 2 usage error.

Usage:
  scripts/build_identity.py                          # record what is served
  scripts/build_identity.py --expected efb1357-dirty # compare, fail on mismatch
  scripts/build_identity.py --require                # reject unknown builds
  --base-url URL     defaults to $SPAGO_BASE_URL, else http://127.0.0.1:8000
  --timeout SECONDS  HTTP timeout, default 10
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.error
import urllib.request

UNKNOWN = "unknown"


def _fetch_health(base_url: str, timeout: float) -> dict:
    """One bounded GET of /healthz; any failure raises, the caller reports it."""
    url = base_url.rstrip("/") + "/healthz"
    request = urllib.request.Request(url, headers={"Accept": "application/json"})
    with urllib.request.urlopen(request, timeout=timeout) as response:
        body = json.loads(response.read().decode("utf-8"))
    if not isinstance(body, dict) or "build_id" not in body or "build_source" not in body:
        raise ValueError("the payload carries no build identity (server older than B-34?)")
    return body


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Compare the served /healthz build identity with an expected one."
    )
    parser.add_argument(
        "--expected",
        default=None,
        help="the identity this run is recorded against; defaults to $SPAGO_BUILD_ID",
    )
    parser.add_argument(
        "--require",
        action="store_true",
        help="fail when the served identity is unknown, even with no expectation",
    )
    parser.add_argument(
        "--base-url",
        default=os.environ.get("SPAGO_BASE_URL") or "http://127.0.0.1:8000",
        help="defaults to $SPAGO_BASE_URL, else http://127.0.0.1:8000",
    )
    parser.add_argument("--timeout", type=float, default=10.0, help="HTTP timeout in seconds")
    args = parser.parse_args(argv)

    expected = args.expected
    if expected is None:
        expected = os.environ.get("SPAGO_BUILD_ID", "").strip() or None
    if expected == UNKNOWN:
        print(
            "usage error: --expected unknown is not an expectation; use --require to "
            "reject unknown builds, or omit --expected to record one",
            file=sys.stderr,
        )
        return 2

    try:
        health = _fetch_health(args.base_url, args.timeout)
    except Exception as exc:  # unreachable/unreadable server is not a pass
        print(f"FAILED: cannot read a build identity from {args.base_url}/healthz: {exc}")
        return 1

    served = str(health["build_id"]).strip()
    source = str(health["build_source"]).strip()
    print(f"base_url:        {args.base_url}")
    print(f"build_id:        {served}")
    print(f"build_source:    {source}")
    print(f"api_version:     {health.get('api_version')}")
    print(f"dataset_version: {health.get('dataset_version')}")
    print(f"status:          {health.get('status')}")

    served_unknown = served == UNKNOWN or source == UNKNOWN
    if expected is not None and served != expected:
        print(f"MISMATCH: expected build_id={expected}, served build_id={served}")
        return 1
    if args.require and served_unknown:
        print("FAILED: the served build identity is unknown; build with scripts/build_app.sh")
        return 1
    if expected is not None:
        print(f"OK: served build_id matches {expected}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
