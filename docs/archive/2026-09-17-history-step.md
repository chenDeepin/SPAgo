# B-43 — one navigation step, one history entry

> Archived 2026-09-17 — delivered. Register: `docs/plans/backlog.md` §1 (delivered
> table). Check: `apps/web/scripts/history-step-check.mjs`.

Class LATER · P3 (first among the ungated defects) · Round: implementation round 4,
2026-09-17.

## Vision alignment

`PROMPT.md` §2.5 / `AGENTS.md` §3: the workspace must behave the way a browser user
expects, and Back is the affordance a scientist uses to return to the question they
were on. This is a defect in navigation that already shipped, not a new surface.

## Reproduced before the fix

On the shipped build (`bf365a1-dirty`), from a stored investigation
(`?q=IL6&t=5ed5e9f2-…`) searching `DEMO-PATENT-A`:

```
in target:    history.length 2,  ?q=IL6&t=5ed5e9f2-…
after search: history.length 4,  ?q=DEMO-PATENT-A     ← two entries pushed
Back once:    ?q=DEMO-PATENT-A                        ← a duplicate of the current entry
Back twice:   ?q=IL6&t=5ed5e9f2-…                     ← only now back at the target view
```

Cause (`App.tsx::openPatent`): when a target scope was open it pushed the new query
state to leave the scope, and then pushed the *same* state again as "a new query is a
navigation step". Both pushes carried identical state, so the extra entry was invisible
until the user pressed Back.

## The change

One state, one push, and "re-open the record already on screen" stays a non-navigation
data refresh — except when it also leaves a target scope, which *is* the step Back has
to undo.

```ts
const leavingTarget = resolvedTargetId !== null;
const sameQuery = value === submittedQuery;
if (sameQuery) queryClient.invalidateQueries({ queryKey: ["patent", value] });
if (sameQuery && !leavingTarget) return;
setSubmittedQuery(value);
updateUrl({ q: value, doc: null, c: null, t: null }, "push");
```

## Verified after the fix

On `bf365a1-dirty` (this round's build), same script, same steps:

```
in target:    history.length 2,  ?q=IL6&t=5ed5e9f2-…
after search: history.length 3,  ?q=DEMO-PATENT-A     ← one entry
Back once:    ?q=IL6&t=5ed5e9f2-…, candidate table visible
```

The regression the item named is pinned in the same run: with the target view's
threshold override set (`?q=IL6&t=…&th=1`), searching a publication and pressing Back
**once** restores that entry **with its filter state** (`th=1`, candidate table
visible) — B-39's per-entry state survives the round trip.

`npm run test:e2e` **8 passed** on the rebuilt stack (the smoke, stale-response,
save-reopen and export specs all exercise search/navigation paths).

## Limits

- One browser, one viewport, one stored investigation; the check asserts URL state,
  history length and the visible table, not a rendered Back button in another browser.
- The check script is not wired into CI; it is a repeatable local measurement
  (`node scripts/history-step-check.mjs` from `apps/web`).
- No other navigation path was re-audited: the fix is local to `openPatent`, which the
  item identified as the owner of the "show this patent" step.
