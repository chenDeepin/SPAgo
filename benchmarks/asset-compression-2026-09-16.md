# Served-asset compression: what the first editor open transfers now (2026-09-16)

Backlog item B-15. Method: the same one the deferral was traded against in
`online08-structure-editor-2026-09-16.md` — measure the bytes the *server* sends and
the request the *browser* makes on a served build, not a bundle listing. The
difference here is that the before and after runs are the same container rebuilt,
with one middleware added.

Nothing in this record is estimated from file sizes: the before column is what the
running container returned, the after column is what the rebuilt container returns.

## Environment

| Item | Value |
| --- | --- |
| Build | `apps/web/dist` from the working tree (2026-09-16 18:18 +08:00), served by `spago-app:m0` |
| Before | image built 2026-09-16 19:29 +08:00 — `uvicorn` + `StaticFiles`, no compression middleware |
| After | same image rebuilt 2026-09-16 19:35 +08:00 with `GZipMiddleware` (level 6, `minimum_size` 500, thread threshold 64 KiB) |
| Navigation | `http://127.0.0.1:8000/?q=DEMO-PATENT-A` (synthetic fixture: 1 family, 10 compounds) |
| Browser | Google Chrome for Testing, CDP-driven; HTTP cache disabled for the run (`Network.setCacheDisabled`) |
| Server | One uvicorn worker, loopback |

## What the server sends (curl, per asset)

`Accept-Encoding: gzip` on every request; every gzipped response carries
`vary: Accept-Encoding`, and the streamed ones carry no `content-length`.

| Asset | Raw | Before | After | Ratio |
| --- | --- | --- | --- | --- |
| `index-CtDUnceZ.js` (entry) | 363,898 | 363,898 | 107,024 | 3.40× |
| `index-DaYA85C0.css` (entry) | 28,355 | 28,355 | 5,437 | 5.21× |
| `StructureSearchDialog-O13VxRDH.js` | 7,762,855 | 7,762,855 | 1,266,610 | 6.13× |
| `StructureSearchDialog-DZ5BIR34.css` | 183,473 | 183,473 | 28,734 | 6.38× |
| `indigoWorker-d22340fa-C3OLXq7_.js` | 75,705 | 75,705 | 24,467 | 3.09× |
| `index.modern-55d8e3ef-B9wOXvz_.js` | 444,103 | 444,103 | 134,580 | 3.30× |
| `indigo-ketcher-1.46.0-f_xBxuuS.wasm` | 11,803,444 | 11,803,444 | 3,780,530 | 3.12× |
| **First paint (entry JS + CSS)** | 392,253 | 392,253 | **112,461** (~0.11 MB) | 3.49× |
| **First open of the structure dialog** (dialog JS + CSS, worker, `index.modern`, WASM) | 20,269,580 (~19.33 MiB) | 20,269,580 | **5,234,921** (~4.99 MiB) | 3.87× |

`Accept-Encoding: identity` returns the raw bytes with `vary: Accept-Encoding` and the
original `content-length`, so a client that cannot decompress is unaffected and a
shared cache keys on the encoding.

## What the browser received

Same click, cache disabled, one run each. `encodedBodySize` / `decodedBodySize` are
the page's own resource-timing values.

| Asset | Before transfer | After transfer | After decoded |
| --- | --- | --- | --- |
| `StructureSearchDialog-O13VxRDH.js` | 7,763,155 | 1,266,910 | 7,762,855 |
| `StructureSearchDialog-DZ5BIR34.css` | 183,773 | 29,034 | 183,473 |
| `indigoWorker-d22340fa-C3OLXq7_.js` | 76,005 | 24,767 | 75,705 |
| `index.modern-55d8e3ef-B9wOXvz_.js` | 444,403 | 134,880 | 444,103 |

The Indigo WASM (11.8 MB → 3.78 MB) is fetched **inside** the Indigo web worker, which
page-level resource timing does not see; the app's access log is the witness that the
browser asked for it, and the curl row above is the measurement of what that request
now receives. In the after run the worker **revalidated** its cached copy (`304 Not
Modified` in the log), so this record claims no browser-side after figure for the WASM
transfer.

## Time to a usable editor

| Observation | Before | After |
| --- | --- | --- |
| Click "Structure ▾" → editor ready (`.structure-editor-loading` gone) | 641 ms | 582 ms |
| Editor surface present (`.Ketcher-root`), error banner | present, none | present, none |

**This is not a latency claim.** 641 ms vs 582 ms on loopback is inside run-to-run
noise and the two runs are not like-for-like: the before run downloaded the WASM cold,
the after run revalidated it from the browser cache. The claim of this record is the
byte column above — on a remote host the transfer term dominates and the difference is
the operator's to measure (the worksheet in `docs/runbook.md` §H9 has the row).

## Cost of compressing

Compression happens in the app process on a worker thread (chunk size 64 KiB matches
`FileResponse`'s stream chunk, so no file chunk is compressed in the event loop).

| Check | Result |
| --- | --- |
| One dialog JS, level 6 vs level 9 | 106 ms → 1,265,793 B vs 234 ms → 1,237,545 B (`gzip -9` comparison) |
| The WASM, level 6 vs level 9 | 349 ms → 3,784,352 B vs 628 ms → 3,759,279 B |
| `/healthz` while three cold gzipped WASM transfers are in flight | 3.5–7.8 ms over 10 samples (no event-loop stall) |

Level 6 is the shipped choice: level 9 buys 48 KB of a 5.2 MB first open for twice the
CPU.

## What this record does not say

- Not a capacity or user-latency claim: one worker, one browser, loopback, a synthetic
  10-compound fixture.
- Not a brotli measurement. Brotli would need a new dependency and remains the
  operator's proxy option (`docs/runbook.md` §H2).
- Not a statement about a proxy in front: the middleware passes through any response
  that already carries `content-encoding`, and skips 206 partial responses, so a
  compressing ingress does not double-encode — but no proxy was exercised here.
- The screenshots in `docs/plans/ui-round-verification/` (`b15-editor-before.png`,
  `b15-editor-after.png`) are behaviour evidence that the editor still opens and draws
  its surface; they are not a rendering-quality review.

## Reproduce

```bash
docker compose up -d --build app                      # serves the same dist through the app
# Per-asset wire bytes and headers (before/after the change, same commands):
for f in index-*.js StructureSearchDialog-*.js indigo-ketcher-*.wasm; do
  curl -s -H 'Accept-Encoding: gzip' -o /dev/null -w "%{size_download} $f\n" \
    "http://127.0.0.1:8000/assets/$f"
done
curl -s -H 'Accept-Encoding: gzip' -D - -o /dev/null \
  http://127.0.0.1:8000/assets/index-CtDUnceZ.js | rg -i 'content-encoding|vary|content-length'
# In the browser: /?q=DEMO-PATENT-A, click "Structure ▾", read encodedBodySize in the
# network panel; the WASM appears only in the worker's network context — the app log
# is the easier witness: docker compose logs app | rg 'assets/'
# Server-side cost of the chosen level:
python3 - <<'PY'
import gzip, time, pathlib
p = next(pathlib.Path("apps/web/dist/assets").glob("indigo-ketcher-*.wasm"))
raw = p.read_bytes()
for level in (6, 9):
    t = time.perf_counter(); out = gzip.compress(raw, level, mtime=0)
    print(level, len(out), round((time.perf_counter() - t) * 1000), "ms")
PY
```
