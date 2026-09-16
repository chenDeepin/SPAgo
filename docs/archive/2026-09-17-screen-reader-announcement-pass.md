# B-44 — the screen-reader announcement pass, and B-08's source-capability check

> Archived 2026-09-17 — delivered. Register: `docs/plans/backlog.md` §1 (delivered
> table), B-46 and B-47 (what the round recorded instead of fixing).

Date: 2026-09-17 · Class NEXT · P2 (B-44) and LATER · P3 (B-08) · Commit round:
implementation round 2.

## Vision alignment

`PROMPT.md` §2.5 / `AGENTS.md` §3 — the tables are the product's main object, and a
scientist who reads them with assistive technology must be told what a cell means and
where they are. B-44 is not a new surface: it is the verification B-19 claimed and did
not perform, and the defect it found was a false statement the interface made about its
own data ("1 row"). B-08 is the honesty rule behind `docs/online-capability.md` §8: a
gap statement may only claim what was actually checked.

## B-44 — what was asked, what was done

**Asked.** An announcement pass with a named reader/platform, recorded (what was read,
at which row, with which control); the keyboard pass re-run against the same build so
the two are not mixed; any defect found fixed with a spec or recorded as its own item.

**Done.** `apps/web/scripts/at-pass.mjs` runs a real screen reader — Orca 42.0 over
speech-dispatcher 0.11.1 — against Chrome 142 with `--force-renderer-accessibility`,
tabs into each table from the top of the document, and records per step: the focused
DOM element, every `SPEECH OUTPUT` utterance Orca produced, and the accessibility tree
Chrome exposed (`Accessibility.getFullAXTree` over CDP). It re-verifies the B-19
keyboard rules in the same run so the two passes cannot be confused. The stream is
committed verbatim as `benchmarks/screen-reader-pass-2026-09-17-transcript.txt` and
annotated in `benchmarks/screen-reader-pass-2026-09-17.md`.

### Two session faults, and why they are part of the deliverable

Both looked like a healthy pass and were not:

1. **No active window.** A reader announces the active window only. `Page.bringToFront`
   left `_NET_ACTIVE_WINDOW` at `0x0` in this session; Orca logged
   `[frame | …] lacks state active` 137 times in one run and announced nothing. The
   first pass therefore produced a nearly empty stream that could easily have been
   written up as "the tables announce fine". `apps/web/scripts/x11-focus.py` sets the X
   input focus directly (libX11 through ctypes — no new package), and the harness
   re-asserts it every 250 ms during a step because other windows on this desktop claim
   activation while it runs.
2. **A wedged speech server.** A stuck speech-dispatcher left Orca blocked in
   `SET self CLIENT_NAME`, its debug file ending at "Launching version 42.0" with no
   error. The pass runs a private daemon whose default output module is `dummy`: it
   answers every utterance, makes no sound, and the spoken text is read from Orca's own
   debug lines.

`AGENTS.md` §27 now carries the rule this produced: an empty announcement stream is a
session fault to diagnose, never evidence that the interface announces correctly.

### The defect, and the fix

Before: **"table with 1 row 6 columns"** for a ten-row table (`50caf8f-dirty`).
The platform table counted only the header row (`AtkTable nRows=1 nColumns=6`) because
no data cell carried `role="cell"`; data-row children were `generic`/`none`, with no
cell object, no column index and no header association.

Fix: `role="cell"` on every direct child of a data row in `CompoundTable.tsx` and
`CandidateTable.tsx`, with the constraint recorded as a comment where the next reader
meets it.

After: **"table with 11 rows 6 columns"**, cells exposed with content and index (70
cells in the candidate table's tree). The before/after was measured on one build by
stripping the attribute in the page at runtime and re-reading the tree — the only
difference between the two shapes — and the platform table interface moved from
`nRows=1` to `nRows=11`.

### Recorded instead of fixed (now B-46)

- Each data row is its own tab stop: the transcript records "30 further Tab press(es)
  still landed inside rows" after the first row, and the IL6 investigation holds 157.
- No arrow-key movement between rows or cells; a focused row announces nothing (the
  content lives in its cells).
- Entering the candidate table announced the select-all checkbox without the table's
  own description in this run, which the compound table did announce — unexplained,
  handed to B-46 with its acceptance.

A roving-tabindex grid changes the keyboard model B-19 verified, so it needs its own
keyboard *and* reader pass; bundling it into this round would have been a second,
unverified change.

## B-08 — the negative result

A bounded, read-only check (worker-run, coordinator-recorded) read the REST adapter's
stored-field set, made two calls to the adapter's own documented endpoint
(`getLigandsByUniprot`, IL-6 `P05231`, trypsin `P07477`), read BindingDB's documented
REST reference, and inspected the operator release's 640-column header with a 5 000-row
population sample. Every affinity row of the live payload carries four keys (monomer id,
SMILES, affinity type, value); no documented path and no release column supplies an
assay description or variant/mutation context; `PubChem AID` is the one assay link and
belongs to PubChem (B-07). Species is already covered by the B-23 snapshot path.

The item's premise needed one correction, which is now in the capability page: the
`assay_description` on a BindingDB REST row is **a note SPAgo writes itself**, not a
source's assay text. Nothing was implemented, which is the honest outcome the item's own
scope allowed ("If no, record the negative result and close the item"). Left over and
recorded as B-47: the release's `pH` and `Temp (C)` columns, which no path maps.

## Verification performed in this round

| Check | Result |
| --- | --- |
| `scripts/run_checks.sh` (backend suite + frontend build), before and after | **831 passed**, build clean, exit 0 |
| `npm run test:e2e` on the rebuilt stack after the fix | **8 passed** (34.5 s) |
| `scripts/build_identity.py --expected $(git describe --always --dirty)` | `OK: served build_id matches 9250b0c-dirty` |
| Announcement pass, both views, build `9250b0c-dirty` | transcript committed; keyboard rules re-verified in the same run |
| Same-build before/after of the cell role | `cell` 70 → 0; platform table `nRows` 11 → 1 |

## Limits

- One reader (Orca 42.0), one browser (Chrome 142), one platform (this X11 desktop), two
  views, one viewport (1600×1000). NVDA/JAWS/VoiceOver, Windows/macOS and the hosted
  deployment are untested.
- Orca's own Ctrl+Alt+arrow table commands are untested: Orca grabs them at the X level
  and synthetic keys never reach the grab. The cell objects and headers are shown to
  exist in the tree the reader reads, which is weaker than a reader reading them.
- The inspector's dialog was not announced although the DOM shows it opening; the stream
  lags the keystroke by up to one step here, so this is an observation, not a finding.
- The pass is manual and desktop-bound: it is not in CI, and B-46's change is what would
  make an automated assertion possible.
- No hosted acceptance, no live-source run beyond B-08's two documented calls, and no
  closed §6 criterion: this round is local evidence with its build identity recorded.
