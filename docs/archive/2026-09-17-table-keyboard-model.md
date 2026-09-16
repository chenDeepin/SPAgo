# B-46 — the keyboard model of the virtualized tables

> Archived 2026-09-17 — **delivered**. Register: `docs/plans/backlog.md` §1 (delivered
> table). Measurements and the reader transcript: `benchmarks/table-keyboard-2026-09-17.md`
> with `benchmarks/table-keyboard-2026-09-17-transcript.txt`.

Class NEXT · P2 (head) · Round: implementation round 3, 2026-09-17.

## Vision alignment

`PROMPT.md` §2.5 / `AGENTS.md` §3: the two virtualized tables are where the workflow's
objects are chosen and read, and a scientist who works by keyboard or through a reader
must reach a row and read it with the keys a table implies. This closes what B-44's
pass measured, not a new surface: no layout, no new control, no new destination.

## What was measured (B-44's pass, build `9250b0c-dirty`)

- Every data row carries `tabIndex={0}`: after the first row the pass recorded "30
  further Tab press(es) still landed inside rows", and the IL6 investigation holds 157
  candidates with a checkbox and a structure button inside each — hundreds of Tab
  presses to cross one table.
- No arrow key moves between rows or cells (the row handler only acts on Enter/Space).
- Focusing a data row announces nothing: the row has no accessible name, and the
  content lives in its cells.

## Change

The ARIA grid pattern, in the tables' existing layout:

1. **One tab stop per table.** A row's `tabIndex` becomes roving — `0` for the current
   row, `-1` for the rest. The current row is the inspected row when it is loaded,
   otherwise the row the user last moved to, otherwise the first.
2. **Arrow keys move inside.** `ArrowDown`/`ArrowUp` move the current row by one,
   `Home`/`End` jump to the first/last; the virtualizer scrolls the target into view and
   focus follows it after the row renders. Enter/Space keep B-19's behaviour.
3. **Nested controls follow the current row.** The row checkbox, the structure preview
   button, the evidence link and "Show all occurrences" are tabbable only inside the
   current row, so Tab crosses the table in a fixed number of stops that does not grow
   with the row count. Reaching a control in another row means moving to that row first
   — the standard composite-widget trade, and it is stated in the UI's own terms in the
   plan record rather than half-implemented.
4. **A row that takes focus becomes the current row**, so a mouse click and a Tab both
   leave the keyboard where the user is looking.

## Acceptance

- Tab crosses each table in a fixed number of stops (measured before/after at 1600×1000
  on a stored investigation, not asserted from the DOM).
- From the current row, ArrowDown/ArrowUp/Home/End move focus between rows, including
  across the virtual window (the row is scrolled into view and focus lands on a live
  element), and each move is read by Orca.
- B-19's rules still hold through the reader on the same build: Space on a row checkbox
  selects without inspecting, Enter on a row inspects.
- A row's cells are reachable and their content is announced; what the reader says for
  the row itself is recorded, and if it stays silent the row gains a name and the
  change is measured again.
- `scripts/run_checks.sh` and `npm run test:e2e` stay green; the record names the build
  identity and states what the pass does not prove.

## Not in scope

Making the *cells* focus targets (a full two-dimensional grid with cell-level arrow
navigation) unless the reader pass shows the row-level model is not enough; the
evidence inspector and the dialogs (B-19/§27 already cover their focus behaviour);
bulk-selection UI.

## Outcome (2026-09-17)

Delivered as planned, with two things the plan did not anticipate:

- **Rows needed a name.** Focus moves between rows, not cells, so the row's
  `aria-label` is the reader's only channel; without it the pass recorded silence on
  every arrow move. Each row now announces its identity and its decision-relevant
  content, with the `of N` taken from the result set's total so it agrees with the
  table's own announced row count.
- **Focus must follow a held key.** Reading the current position back from the focused
  element made rapid `ArrowDown` presses stall on the row they were about to leave (60
  presses advanced 30 rows in the first attempt); the logical position is tracked in a
  ref, and 60 rapid presses now advance 60 rows across the virtual window.

Measured before/after and what the reader says: `benchmarks/table-keyboard-2026-09-17.md`.
Not delivered, and stated in that record: cell-level arrow navigation (the grid's second
dimension), and any claim about Orca's own Ctrl+Alt+arrow commands, which this harness
cannot drive.

Verification on the round's build (`0d1d983-dirty`): `npm run check:table-keyboard`
(tab stops 30 → 3 compound, 1 candidate; arrows and Home/End move and land),
`npm run at-pass` (rows announced, B-19 rules re-verified through the reader),
`npm run test:e2e` 8 passed, `scripts/run_checks.sh` green.
