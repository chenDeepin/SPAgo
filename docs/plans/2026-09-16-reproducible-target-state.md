# B-39 — Reopen an investigation with its filters and policy

Date: 2026-09-16 · Register: `docs/plans/backlog.md` B-39 · Class NEXT · P2.

## Vision alignment

`PROMPT.md` §2.5 / AGENTS.md §19: return to the same target question and its
verdict settings. Before this round the evidence-class filter, modality
expansion and threshold override lived only in React state — a refresh, a
shared link or Back/Forward silently returned the deployment defaults, so the
same URL could mean different questions. After it, the URL states the rule the
view was asked under.

## Delivered

- `state/url.ts`: `ev` (evidence class, validated against the five-class
  vocabulary the select offers), `mod` (=all), `th` (threshold in µM, bounded
  0.0001–1000) — validated on read; an unknown class or out-of-bounds
  threshold is dropped to its default, never smuggled into a request. The
  fields are optional in `UrlState`: every scope-opening call site that builds
  a fresh state keeps meaning "new scope, default filters" without listing
  them. Only identifiers and bounded scalars are encoded — no SMILES, no
  result sets (§19).
- `App.tsx`: the three states initialize from the URL, the popstate subscriber
  restores them per history entry, and each control's change replaces the
  current entry with its own filter state — so Back/Forward restores the
  question *and* its rule.

## Verification (browser, rebuilt stack `bf2e925-dirty`, 1600×1000)

- Applying all three controls writes `ev=…&th=0.001&mod=all` into the URL;
  **reload** restores the select value, threshold input and checkbox exactly.
- A hand-edited invalid state (`ev=made_up_class&th=99999`) is dropped, not
  applied: the select reads "any", the threshold shows the deployment default
  (10 µM), and the verdict strip visibly computes under 10 µM — the explicit
  outcome for invalid/older state.
- **Back/Forward**: navigating from the filtered IL6 view to the demo family
  and back restores `ev=functional_effect`, `th=1` from the history entry.
- Changed source data stays labelled as a current re-evaluation: the counts
  are recomputed server-side on every read (existing contract), so a reopened
  filter state never renders stale numbers.

## Found along the way (recorded as B-43)

Opening a patent from inside a target view pushes **two** history entries
(`openPatent` pushes once for the target-mode switch and once for the query),
so browser Back needs two presses to leave the newly opened family. A
pre-existing quirk, unrelated to filter state; recorded in the register
rather than fixed here.

## Not verified

Structure-search snapshots remain a later scope decision (per the item);
assistive-technology announcements remain open from B-19.
