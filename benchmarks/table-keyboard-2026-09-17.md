# The tables' keyboard model — 2026-09-17

Register item **B-46**, the two keyboard-model defects and the silent row focus that
B-44's announcement pass measured. This is the record of the change, the before/after
measurements and what remains.

Built and verified on this workstation against the running compose stack at
`http://127.0.0.1:8000`, `/healthz` `build_id=0d1d983-dirty`,
`dataset_version=demo-fixture-v1`, viewport 1600×1000 (X11 `DISPLAY=:1`).

| | |
| --- | --- |
| Keyboard measurement | `apps/web/scripts/table-keyboard-check.mjs` (`npm run check:table-keyboard`) — DOM-level, no reader needed |
| Reader pass | `npm run at-pass` (Orca 42.0 through speech-dispatcher), transcript `table-keyboard-2026-09-17-transcript.txt` |
| Views | `?q=DEMO-PATENT-A` (10 data rows) and `?q=IL6&t=5ed5e9f2-c733-543f-96dd-f58ae5a1f618` (157 candidates, 100 loaded) |

## What was wrong

- Every data row carried `tabIndex={0}` plus its own nested controls, so Tab crossed
  the table one row at a time: B-44's pass recorded "30 further Tab press(es) still
  landed inside rows" after the first row, on a table that can hold hundreds.
- No key moved between rows (the row handler acted on Enter/Space only).
- Focusing a row announced nothing, because the row had no accessible name — and, with
  row-level focus, the row's name is the reader's only channel (the cells are not focus
  targets in this model).

## The change

`CompoundTable.tsx` and `CandidateTable.tsx`:

1. **One tab stop per table.** A row's `tabIndex` is roving — `0` for the current row,
   `-1` for the rest; the current row is the inspected row when it is loaded, else
   where the user last moved to, else the first. Nested controls (row checkbox,
   structure preview, evidence link, "Show all occurrences") are tabbable only inside
   the current row, so the number of stops does not grow with the row count.
2. **Arrow keys move inside.** `ArrowDown`/`ArrowUp` move one row, `Home`/`End` jump to
   the first/last. The virtualizer scrolls the target into view and focus follows it
   after the row renders (retried for a few frames, because a jump across the virtual
   window renders the target on a later commit). The logical position is tracked in a
   ref rather than read back from the focused element: a held arrow key repeats faster
   than focus can move, and reading the DOM would stall on the row it is about to leave.
3. **A row is a named focus target.** Each row carries an `aria-label` with its
   identity and the decision-relevant content its cells hold — compound: `Compound 3 of
   10: CMWTZPSULFXXJA-SECBINFHSA-N, C14H14O3, 2 measurements, Example 11`; candidate:
   `Candidate 2 of 157: WEBQKRLKWNIYKK-UHFFFAOYSA-N, weak IC50 13810 nM, measured
   binding, no patent mapping`. The `of N` is the result set's own total, so the name
   and the table's announced row count agree.
4. A row that takes focus becomes the current row, so a mouse click and Tab leave the
   keyboard where the user is looking.

## Measured

DOM-level (`npm run check:table-keyboard`, this build):

| | Before (B-44's pass) | After |
| --- | --- | --- |
| Tab stops inside the compound table | 30 further presses still inside rows after the first row | **3** (current row's checkbox, structure preview, evidence link) then out |
| Tab stops inside the candidate table | rows to the end of the loaded page | **1** (current row's checkbox) then out |
| Arrow keys | none | `ArrowDown` 0→5, `End` → last row, `Home` → first row, focus lands on the rendered row each time |
| 60 rapid `ArrowDown` presses | — | row 2 → **row 62**, 16 rows rendered, no press lost across the virtual window |
| Enter on the current row | opens the Evidence inspector | unchanged (1 dialog) |
| Space on a row checkbox | selects, does not inspect | unchanged (inspector 0, one box checked) |

Reader (`npm run at-pass`, transcript committed):

```
Compounds in family DEMO-FAMILY-1.
table with 11 rows 6 columns
Select all loaded compounds check box not checked.
Compound 1 of 10: ABBQHOQBGMUPJH-UHFFFAOYSA-M, C7H5NaO3, no activity shown, Example 12.
Compound 2 of 10: BSYNRYMUTXBXSQ-UHFFFAOYSA-N, C9H8O4, 2 measurements, 2 patent labels.
…
Select all loaded candidates check box not checked.
Candidate 1 of 157: UPJFTVFLSIQQAV-KOLCDFICSA-N, active IC50 1630 nM, measured binding, no patent mapping.
```

and the B-19 rules re-verified in the same run on the same build:

```
> after Space on a row checkbox — inspector open: false, checked row boxes: 1
> after Enter on the focused row — dialogs: ["Evidence inspector"]
```

Green elsewhere: `npm run test:e2e` **8 passed** on the rebuilt stack;
`scripts/run_checks.sh` (backend suite + frontend build) run for this round.

## What this does not prove, and what is left

- **Cells are still not focus targets.** Arrow keys move between rows; there is no
  left/right movement *into* a cell, so "the focused cell announces its column header"
  is not delivered — the row's name carries the content instead. Orca's own
  table-navigation commands (Ctrl+Alt+arrows) remain untested here, because Orca grabs
  them at the X level and synthetic keys never reach the grab; a real user with the
  reader attached can still use them. A two-dimensional grid is the next step if a user
  needs cell-level reading, and it is not claimed by this round.
- **The `of N` position is the result set's total**, so a row pinned outside the current
  filter (shown and labelled, not counted into the total, per the D2 contract) can read
  as one position past the end.
- One reader, one browser, one platform, one viewport — the same limits B-44's record
  states. The pass is manual and desktop-bound; `check:table-keyboard` is the part that
  could be automated.
- The candidate table still does not announce its own table description when focus
  enters it in this harness (the compound table does); that observation is unchanged by
  this round and remains unexplained.
