# B-15 — Compress served assets (Ketcher first open)

Round opened 2026-09-16. Class **NEXT · P1 · S–M**. Register entry:
`docs/plans/backlog.md` §B-15. Measurement it answers:
`benchmarks/online08-structure-editor-2026-09-16.md` (first dialog open 20,269,580 B raw,
5,191,491 B as `gzip -9`; the shipped container sends no `content-encoding`).

## What a user can do afterwards that they cannot do now

Open the structure editor for the first time and transfer about a quarter of the bytes
(measured below), with no proxy, no CDN and no operator configuration — the same
`docker compose up -d --build` install (`AGENTS.md` §24) that is the supported path
today. Until now the only compression in the deployment was a *duty* assigned to an
ingress that a compose install does not have (`docs/runbook.md` §H2).

## The problem, in the current checkout

- `spago_core/main.py` mounts `StaticFiles` at `/` and adds no compression middleware;
  uvicorn sends `content-length` and the bytes as they sit on disk.
- Verified on the running `spago-app:m0` container before the change (2026-09-16,
  127.0.0.1:8000): `GET /assets/indigo-ketcher-1.46.0-f_xBxuuS.wasm` returns
  11,803,444 B with **no** `content-encoding` and no `vary`, also when the request
  sends `Accept-Encoding: gzip`; same for the 7.76 MB dialog bundle and the entry
  chunks. That matches the recorded benchmark rather than replacing it.
- The runbook's "ingress duties" table tells the operator to enable gzip/brotli — a
  correct instruction for a proxied host and a dead end for `docker compose up`.

## Decisions

- **D1 — The app compresses; the proxy stays optional.** Compression is served from the
  image the product already builds, so the capability does not depend on a component
  that the supported install does not include. A reverse proxy in front may still
  compress further (brotli) or pass the gzip through; it must not double-encode, which
  the middleware's pass-through rule makes safe (an already-encoded response is never
  re-encoded).
- **D2 — Starlette's own `GZipMiddleware`; no new service, no new dependency.** It ships
  with FastAPI, so §6 (no new infrastructure) and §23 (dependency + notices) are not
  touched; a proxy container or a vendored static-file server would both be larger
  changes with the same measured effect. §33's bar (ADR) is for architecture, and this
  is a middleware line in the existing process — recorded here instead.
- **D3 — Level 6, measured rather than assumed.** On this machine, one core: dialog JS
  7,762,855 B → 1,265,793 B in 106 ms (level 9: 1,237,545 B in 234 ms); WASM
  11,803,444 B → 3,784,352 B in 349 ms (level 9: 3,759,279 B in 628 ms). Level 9 buys
  48 KB of 5.2 MB for twice the CPU, so 6 is the default here and the numbers are in the
  record.
- **D4 — Big bodies compress off the event loop.** `StaticFiles`/`FileResponse` send
  64 KiB chunks; the middleware only uses a worker thread for chunks ≥ its
  `thread_minimum_size`, so the default 128 KiB would put every file chunk on the event
  loop. The threshold is set to 64 KiB to match the chunk size, and the record measures a
  concurrent `/healthz` during a cold 11.8 MB fetch as the honest cost check.
- **D5 — Measure on the wire, not from the bundle listing.** The re-measurement is a
  browser run against the rebuilt container (CDP `encodedDataLength` plus the served
  response headers) with the same click and the same app-log witness as
  `benchmarks/online08-structure-editor-2026-09-16.md`, so before/after are the same
  method. Loopback is not a network: the byte delta is the claim, the localhost
  editor-ready time is recorded as a non-claim, exactly as the original record did.
- **D6 — API responses are compressed by the same middleware and are not the goal.**
  JSON above the minimum size gets the same treatment (a bonus, measured only for
  sizes); no per-route tuning, no separate compression of exports.
- **D7 — Brotli stays out of the image.** It would add a dependency (`brotli`) for a
  ~15 % further reduction on these assets; a beta's first editor open is already
  addressed, and the proxy row in `docs/runbook.md` §H2 keeps brotli as the operator's
  option. Revisit only with a measured need.

## Checks to run

1. Unit/API tests: a compressible response over the minimum is gzipped when the client
   accepts gzip (with `vary: accept-encoding` and a matching `content-length`), sent
   identity when it does not, small bodies untouched, `application/wasm` compressed
   through a real `StaticFiles` mount, `image/png` excluded, and a body that already
   carries `content-encoding` passed through.
2. The app enables it: `create_app()` configures `GZipMiddleware` with the chosen level
   and threshold (asserted against the app's middleware stack, no web build required).
3. Rebuild `spago-app:m0`, then `curl -H 'Accept-Encoding: gzip'` per asset: expect
   `content-encoding: gzip`, no `content-length` for the streamed files, and
   `vary: accept-encoding`.
4. Browser: open `/?q=DEMO-PATENT-A` on the rebuilt container, click "Structure ▾", read
   `encodedDataLength` per asset from CDP and the time to a usable editor; concurrency
   check for `/healthz` during a cold WASM fetch.
5. Text checks: `git diff --check` on the round's files; docs updated (`docs/runbook.md`
   §H2 duty row, `docs/online-capability.md` §5, this file's Result section,
   `benchmarks/asset-compression-2026-09-16.md`).

## Result

**Delivered 2026-09-16.** `spago_core/main.py` now configures `GZipMiddleware`
(level 6, `minimum_size` 500, thread threshold 64 KiB) as an inner layer of the app;
`services/core/tests/test_served_assets.py` (8 tests) pins both the settings and the
observed behaviour on a real static mount — gzip + `vary` when the client accepts it,
identity when it does not, small bodies untouched, `application/wasm` compressed,
streamed bodies without a stale `content-length`, `image/png` never re-encoded. No
dependency was added, so `AGENTS.md` §23 is not triggered (the middleware is
Starlette's, already part of the FastAPI runtime the image ships); no new service, so
§6 is not engaged — recorded in the file's decisions rather than as an ADR (§33 is for
architecture).

Measured on the rebuilt container, per asset and in the browser
(`benchmarks/asset-compression-2026-09-16.md`):

| | Before | After |
| --- | --- | --- |
| Entry JS + CSS | 392,253 B | **112,461 B** (3.49×) |
| First open of the structure dialog | 20,269,580 B (~19.33 MiB) | **5,234,921 B (~4.99 MiB)** (3.87×) |

The browser's own resource timing shows the four page-visible dialog assets arriving at
their compressed sizes with the uncompressed `decodedBodySize`, and the editor opening
with no error banner (`docs/plans/ui-round-verification/b15-editor-after.png`). The
Indigo WASM is measured server-side only: it is fetched inside the worker (page timing
does not see it) and in the browser run the worker revalidated its cached copy, so no
browser-side after figure for the WASM is claimed. Level 6 over 9 (106 ms vs 234 ms for
the dialog chunk, 48 KB saving of 5.2 MB), and `/healthz` answered in 3.5–7.8 ms while
three cold gzipped WASM transfers ran, which is what the 64 KiB thread threshold is
for. The loopback click-to-editor time (641 ms → 582 ms) is recorded as a **non-claim**:
the runs are not like-for-like and the difference is inside noise.

Checks run: the round's 8 tests pass; `tests/test_b23_bindingdb_snapshot.py` and the
full backend suite were re-run after the `scripts/bindingdb_snapshot.py` stdout/stderr
fix that this round also carries (the script's preamble now follows the JSON to stderr
under `--json -`, and its two test-side database URLs keep their password instead of
being masked by `str(engine.url)`) — both defects were found by these tests, not by a
reader. Docs updated: `docs/runbook.md` §H2 (compression is no longer a missing duty),
`docs/online-capability.md` §5, `docs/architecture/overview.md`, `PROMPT.md`,
`benchmarks/README.md`.

Not verified here: any proxy or brotli, a non-loopback network, and the operator's H9
latency row — all recorded as gaps in the benchmark rather than assumed.
