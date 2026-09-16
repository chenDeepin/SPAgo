# B-34 — Distinguishable build identity in verification artifacts

> Archived 2026-09-17 — round closed. Delivered record and open remainder: [backlog register](../plans/backlog.md) §1–§2.

Date: 2026-09-16 · Register: `docs/plans/backlog.md` B-34 · Class CORE · P1.

## Vision alignment

AGENTS.md §36 acceptance shape and `PROMPT.md` §1: a reported result or defect
must be relatable to the build actually served. After this round, `/healthz`
answers that with a build identity distinct from `api_version`, verification
runs state the build they came from, and a recorder can fail a run whose served
identity does not match the build it intended to verify. No new panel, service
or dependency.

## Design

- **Injection**: `SPAGO_BUILD_ID` env var read once at `create_app()` (into
  `app.state`, like `version`), surfaced by `/healthz` as `build_id` plus
  `build_source` (`env` | `unknown`). Missing or blank → explicit `unknown`,
  never guessed from `__version__` (which stays `0.1.0`, a separate concept).
- **Packaging**: `docker/app/Dockerfile` bakes `ARG SPAGO_BUILD_ID=unknown` into
  the runtime image env — the container has no `.git` and never reads one.
  `docker-compose.yml` passes `${SPAGO_BUILD_ID:-unknown}` as the build arg and
  deliberately does *not* set a runtime env (a runtime value would mask the
  identity the image was built with). `scripts/build_app.sh` computes
  `git describe --always --dirty` on the build host and fails loudly when it
  cannot.
- **Recorder**: `scripts/build_identity.py --expected <id> [--require]` fetches
  `/healthz`, compares, and exits non-zero on mismatch, on `unknown` when
  `--require` is given, or when unreachable; it prints api_version,
  dataset_version and status alongside, and refuses `--expected unknown` as a
  usage error.
- **Docs**: README (Distinguishable builds), runbook §1/§5/§H3, capability §1/§6
  recording notes, `.env.example` guarded entry.

## Defect found in review and fixed in this round

`scripts/build_app.sh` as delivered computed `BUILD_ID` but ran
`export SPAGO_BUILD_ID` — exporting the *pre-existing empty variable*, never the
computed one. The first rebuilt image therefore served `build_id: "unknown"`
while the script printed `--expected 12aa498-dirty`. The compose interpolation
tests passed because they set `SPAGO_BUILD_ID` in the shell themselves; the
script's own assembly was what was broken. Fixed
(`SPAGO_BUILD_ID="${BUILD_ID}"; export SPAGO_BUILD_ID`) and the fix is verified
by the end-to-end run below, not by reading the script. Lesson recorded: a
recorder script's own plumbing is part of what the served-artifact check must
exercise.

## Verification

- `services/core/tests/test_b34_build_identity.py` — 6 cases: two builds
  distinguishable, dirty marker carried verbatim, `build_source: env`, missing
  → explicit `unknown`/`unknown`, api_version never promoted, blank treated as
  missing.
- Recorder logic exercised against transient stub servers: match → 0, mismatch
  → 1, `--require` on known → 0, on unknown → 1, unreachable → 1,
  `--expected unknown` → 2.
- **End-to-end on the running stack** (the subagent's deferred item):
  `scripts/build_app.sh` rebuilt the image; `docker compose up -d`; `/healthz`
  served `"build_id": "12aa498-dirty", "build_source": "env"`, and
  `scripts/build_identity.py --expected 12aa498-dirty` exited 0 with the
  recorded comparison. The `-dirty` suffix is honest: the tree carries this
  round's uncommitted changes while the image builds.
- `scripts/run_checks.sh --no-pg` passed; full suite green in the same round
  (779 + 8 B-33 + 6 B-34 cases).

## Not verified

A *clean* checkout's build identity (every build in this round was `-dirty`);
a hosted deployment's identity propagation (B-31's territory). Historical
artifacts are not backfilled with guessed identities.
