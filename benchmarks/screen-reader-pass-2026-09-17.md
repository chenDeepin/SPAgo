# Screen-reader announcement pass over the virtualized tables — 2026-09-17

Register item **B-44** (the assistive-technology half of B-19's acceptance). This is
the record of a real screen reader reading the two virtualized tables, what it said,
the defect it found, and what remains open.

Performed on this workstation, against the running compose stack at
`http://127.0.0.1:8000`, `/healthz` `build_id=9250b0c-dirty`,
`dataset_version=demo-fixture-v1`.

| | |
| --- | --- |
| Reader | Orca 42.0 (desktop layout), via speech-dispatcher 0.11.1 |
| Speech server | a private speech-dispatcher instance whose default output module is `dummy` — it accepts every utterance and produces no audio, so the pass does not disturb the machine's sound; the announcement text is read from Orca's own `SPEECH OUTPUT` debug lines |
| Browser | Google Chrome 142.0.7444.175, launched with `--force-renderer-accessibility` |
| Platform | Linux (Deepin/Ubuntu 22.04 base), X11 `DISPLAY=:1`, shared with the human's own session |
| Viewport | 1600×1000 |
| Views | `?q=DEMO-PATENT-A` (compound table, 10 rendered data rows of 6 columns) and `?q=IL6&t=5ed5e9f2-c733-543f-96dd-f58ae5a1f618` (candidate table, 10 rendered data rows of 7 columns) |
| Harness | `apps/web/scripts/at-pass.mjs` (drives the keyboard and captures the stream), `apps/web/scripts/x11-focus.py` |
| Stream | `benchmarks/screen-reader-pass-2026-09-17-transcript.txt` |

## How it was run

```bash
cd apps/web
DISPLAY=:1 SPAGO_TARGET_ID=5ed5e9f2-c733-543f-96dd-f58ae5a1f618 \
  AT_OUT=benchmarks/screen-reader-pass-2026-09-17-transcript.txt \
  node scripts/at-pass.mjs
```

The harness starts Orca against a debug file, opens each view, tabs from the top of
the document into the table recording (a) which DOM element took focus, (b) every
`SPEECH OUTPUT` line Orca produced, and (c) the accessibility tree Chrome exposed
(`Accessibility.getFullAXTree` over CDP) — roles, names and indexes, not the DOM.
It also re-verifies the B-19 keyboard rules on the same build, so the keyboard pass
and the announcement pass are not mixed.

**Two session prerequisites were the hard part, and both are recorded because a
reader that says nothing looks exactly like a table that announces correctly:**

- *The driven window must hold the session activation.* A reader announces the active
  window only. `Page.bringToFront` left `_NET_ACTIVE_WINDOW` at `0x0` in this session
  and Orca logged `[frame | …] lacks state active` 137 times in one run while
  announcing nothing — the run looked like a clean pass. `x11-focus.py` sets the X
  input focus directly (libX11 via ctypes, no new package) and the harness re-asserts
  it every 250 ms during a step, because other windows on this desktop claim
  activation while the pass runs.
- *The speech server must answer.* A wedged speech-dispatcher made Orca block in
  `SET self CLIENT_NAME` and never reach its main loop; the debug file ended at
  "Launching version 42.0" with no error. The private daemon configured with the
  `dummy` module (`/tmp` config, `-C <dir> -S <socket>`, `DefaultModule dummy`) fixed
  it and keeps the pass silent.

## What the reader announced

Compound table (`DEMO-PATENT-A`), entering the table with Tab:

```
main content
Compounds in family DEMO-FAMILY-1.
table with 11 rows 6 columns
column header.
Select all loaded compounds check box not checked.
…
Select compound ABBQHOQBGMUPJH-UHFFFAOYSA-M check box not checked.
checked                                    ← Space on the checkbox
selected                                   ← row selection
```

Candidate table (`IL6`), same navigation:

```
Select all loaded candidates check box not checked.
```

Cell content is exposed to the reader — the candidate table's accessibility tree in
the same run:

```
row → cell(Select candidate UPJFT…) | cell(Structure for UPJFT…) | cell(UPJFTVFLSIQQAV… C12H18…)
    | cell(active IC50 1630 nM) | cell(small molecule rdkit ·) | cell(measured binding)
    | cell(no patent mapping)
```

Keyboard rules re-verified on the same build (recorded in the transcript):

```
> keyboard rule (B-19) on this build: after Space on a row checkbox — inspector open: false, checked row boxes: 1
> keyboard rule (B-19) on this build: after Enter on the focused row — dialogs: ["Evidence inspector"]
```

## The defect the pass found, and the fix

**Before the fix, a reader was told the compound table had one row.** On the
pre-fix build (`50caf8f-dirty`), the same navigation announced:

```
Compounds in family DEMO-FAMILY-1.
table with 1 row 6 columns          ← the header row was the only row counted
```

Cause, measured on the platform interface: neither table's data cells carried
`role="cell"`, so Chrome's accessibility table counted the header row alone
(`AtkTable nRows=1 nColumns=6`) and exposed no cell objects at all — a data row's
children were `generic`/`none` in the AX tree, with no column index and no header
association.

Fix (`apps/web/src/components/CompoundTable.tsx`, `CandidateTable.tsx`): every direct
child of a data row carries `role="cell"`.

**Same-build before/after**, measured by stripping `role="cell"` in the page at runtime
and re-reading the tree (the only difference between the two rows below is that one
attribute) — candidate table, 10 rendered data rows:

| Tree shape | `cell` | `row` | `columnheader` | data row children |
| --- | --- | --- | --- | --- |
| shipped (after the fix) | 70 | 11 | 7 | `cell` × 7 |
| `role="cell"` removed at runtime | 0 | 11 | 7 | `generic`, `none`, `none`, … |

And on the platform table interface the same change moved the announced table from
`nRows=1` to `nRows=11`, which is what the reader's "table with 11 rows 6 columns"
reports. Browser regression after the change: the eight Playwright specs pass on the
rebuilt stack (`npm run test:e2e`, 8 passed) and the backend suite and frontend build
pass (`scripts/run_checks.sh`, 831 passed).

## Recorded as its own item (B-46), not fixed here

- **One tab stop per data row, no arrow-key cell navigation.** Each row carries
  `tabIndex={0}`, so a reader user crosses the table one Tab at a time: the transcript
  records "30 further Tab press(es) still landed inside rows" after the first row, and
  the IL6 investigation holds 157 rows. The standard grid pattern (a single tab stop
  with arrow-key movement and roving tabindex) is a keyboard-model change with its own
  regression surface, so it is register item **B-46**.
- **Focusing a data row announces nothing.** A row is focusable but has no accessible
  name, and Orca says nothing on row focus — the cell content is only reachable by
  table navigation, which the harness cannot drive here (Orca grabs its commands at the
  X level; Playwright's injected keys bypass the grab, so Orca's own Ctrl+Alt+arrow
  navigation is untested by this pass). Recorded in B-46.
- **Entering the candidate table did not announce the table's own description** in this
  run (the compound table did): only the select-all checkbox was announced. Not
  explained by this pass; recorded in B-46 as a question to answer with the keyboard
  model change.

## What this pass does not prove

- **Orca's own table commands are untested.** Ctrl+Alt+arrow cell/row navigation never
  fired under synthetic keys (see above), so "a reader can move cell by cell and hear
  the column header" is not demonstrated by this record; the cell objects and column
  headers are shown to exist in the tree the reader reads, which is weaker.
- **The inspector's dialog was not announced** even though the DOM shows it opening on
  Enter (asserted in the same run) and Escape closing it. The stream lags the keystroke
  by up to one step in this environment, so this is an observation, not a finding about
  the dialog.
- One reader (Orca 42.0), one browser (Chrome 142), one platform (this X11 desktop, a
  shared session), two views, one viewport. NVDA/JAWS/VoiceOver behaviour, Windows or
  macOS, and a screen reader running on the hosted deployment are untested.
- The pass is manual and desktop-bound: it is not part of CI, and nothing here asserts
  announcements automatically.
- Structure depictions, the evidence inspector's own content, dialogs other than the
  two steps above, and the Chrome companion's side panel were not read by the reader.
