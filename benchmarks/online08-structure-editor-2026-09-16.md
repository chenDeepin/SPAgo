# Structure editor: what the dialog costs and how fast it becomes usable (2026-09-16)

Backlog item B1 (`docs/archive/2026-09-16-backlog-round.md`): the embedded Ketcher
editor was deferred in the UI-review round with a named packaging failure. It is now
embedded, and this record holds the numbers that the deferral was traded against —
the editor is 63× the rest of the application, so "it works" is not the whole answer.

Method: open the served build, click the control a reader clicks, and read the
requests off the server that served them. Nothing here is estimated from bundle
listings alone.

## Environment

| Item | Value |
| --- | --- |
| Build | `apps/web/dist` built 2026-09-16 03:16 +08:00 from the working tree; served by the `spago-app:m0` container at `127.0.0.1:8000` (`web/` copied at image build) |
| Entry chunk | `assets/index-DnRNlgaF.js` (319,633 B) + `assets/index-sKBH5zf0.css` (21,601 B) |
| Dialog assets | `StructureSearchDialog-DPt54ybX.js` 7,762,855 B · `StructureSearchDialog-DZ5BIR34.css` 183,473 B · `indigoWorker-d22340fa-C3OLXq7_.js` 75,705 B · `index.modern-55d8e3ef-DwDsLBz8.js` 444,103 B · `indigo-ketcher-1.46.0-f_xBxuuS.wasm` 11,803,444 B |
| Browser | Google Chrome for Testing 147.0.7727.15 (`--headless=new`), CDP-driven |
| Reproducibility | A rebuild on 2026-09-16 (`npx tsc -b && npm run build`) produced the same asset names and hashes, so the figures belong to this checkout, not to an unknown build |
| Navigation | `http://127.0.0.1:8000/?q=DEMO-PATENT-A` (synthetic fixture: 1 family, 10 compounds) |
| Compression | **none** — the container serves assets with `content-length` and no `content-encoding` (uvicorn + `StaticFiles`) |

The gzip column below is what a compressing reverse proxy in front of a hosted
deployment would send. It is measured with `gzip -9` on the same files, not observed
on the wire.

## Transfer

| Phase | Assets | Raw | gzip (-9) |
| --- | --- | --- | --- |
| First paint (patent view) | entry JS + CSS | 341,234 B (~0.33 MB) | 100,082 B (~0.10 MB) |
| First open of the structure dialog | dialog JS + CSS, Indigo worker, `index.modern` chunk, Indigo WASM | 20,269,580 B (~19.3 MiB) | 5,191,491 B (~4.95 MiB) |

The dialog's own JavaScript (7.76 MB raw, 1.24 MB gzip) is one file; the WASM
engine (11.8 MB raw, 3.76 MB gzip) is a second, fetched **inside the Indigo web
worker** — page-level network tracing does not see it. The list above comes from the
application's own access log for the run:

```
GET /assets/index-DnRNlgaF.js
GET /assets/index-sKBH5zf0.css
GET /assets/StructureSearchDialog-DPt54ybX.js
GET /assets/StructureSearchDialog-DZ5BIR34.css
GET /assets/indigoWorker-d22340fa-C3OLXq7_.js
GET /assets/index.modern-55d8e3ef-DwDsLBz8.js
GET /assets/indigo-ketcher-1.46.0-f_xBxuuS.wasm
```

Each is fetched once: the dialog is a lazy `import()` and the browser caches the
response, so a session pays this on the first open, not on every open, and never on
first paint. `index.modern-CzVmXMnp.js` (1.24 MB) is in `dist` but was **not**
requested in either run — it is a build output the editor's Indigo path does not
load, and this record does not claim otherwise.

## Time to a usable editor

| Observation | Value |
| --- | --- |
| Click "Structure ▾" → editor ready (`.structure-editor-loading` gone, no error banner) | **830 ms** and **860 ms** in two runs |
| Editor surface in the DOM at that point | `.Ketcher-root` present, `document.querySelectorAll("canvas").length === 0` — this version draws the molecule surface as SVG, which is why a canvas-based selector finds nothing in a check |
| Editor errors reported (`onInit` missing, change subscription missing, draft rejected) | none |

830 ms is a **localhost, uncompressed, warm-disk** figure: 20.3 MB over loopback with
the WASM compiled by the same machine that serves it. On a remote host the transfer
term dominates and the number is the operator's to measure (the worksheet in
`docs/runbook.md` §H9 has the row).

## What the browser check confirmed about behaviour

- The dialog opens from the compound table's "Structure ▾" control, scoped to the
  family, and the editor mounts inside it.
- A drawing change reaches the SMILES box. This was **not** true of the first
  integration: `ketcher-core` 3.18 exposes `changeEvent` (a `Subscription` with
  `add`/`remove`), and the earlier `editor.subscribe("change", …)` call was a silent
  no-op — the canvas accepted an edit and the box stayed empty. Fixed in
  `apps/web/src/components/StructureEditor.tsx`; regression evidence is the two
  screenshots below plus the change handler's error banners being absent.
- Neither the drawing nor opening the dialog executes a search: the box is the query,
  and the search runs only on the dialog's explicit action (`AGENTS.md` §15).

Screenshots (local, gitignored — they show a running build):
`docs/plans/ui-round-verification/online08-ketcher-1572.png` (dialog open, empty
canvas) and `online08-ketcher-drawn-1572.png` (after drawing an atom, SMILES box
populated). Viewport 1572×900.

## What this record does not say

- Not a capacity or user-latency claim: one browser, one host, a synthetic 10-compound
  fixture, loopback transfer.
- The gzip figures are computed from the files; the shipped container sends them
  uncompressed. A hosted deployment is expected to compress at the proxy, and this
  record does not verify any proxy.
- No measurement of editor behaviour on large structures, of Indigo operation latency
  after init, of editor memory, or of the dialog on a slow connection.
- The two screenshots are behaviour evidence, not a rendering-quality review; the
  editor's own layout inside the dialog was reviewed in the UI round, not here.

## Reproduce

```bash
docker compose up -d --build                      # serves apps/web/dist through the app container
# In the browser: open /?q=DEMO-PATENT-A, click "Structure ▾", watch the network panel.
# The WASM appears in the worker's own network context; the app log is the easier witness:
docker compose logs app | rg 'assets/'
# Sizes and the gzip comparison:
ls -l apps/web/dist/assets && gzip -9 -c apps/web/dist/assets/StructureSearchDialog-*.js | wc -c
```
