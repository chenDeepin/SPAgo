# B-03 — Tolerant publication-number lookup

**Round:** 2026-09-16 (after B-24) · **Class NEXT · P1** · **Owner:** coordinating agent
**Backlog entry:** `docs/plans/backlog.md` §3 B-03
**Vision served:** `PROMPT.md` §1/§2 (patent → family is the first step of the loop) and
`AGENTS.md` §3/§19. What a user can do afterwards that they cannot do now: **type the
number the way it is written where they found it** — on a slide, in a paper, in an
Espacenet result — and get the family that is already loaded, instead of a denial.

---

## 1. The defect, exactly

`GET /api/v1/patents/{publication_number}` → `services.find_patent` matches
`publication_number = :pn` (exact string equality, unique index). `domain/patent_numbers.py`
already normalizes identifiers for *source-declared* numbers (`patent_tokens`,
`patent_number_match`, ONLINE-06/B-02), but that path is not wired to the search box.

Two consequences, both observed:

1. A stored `WO-2020-123456-A` is not found by `WO2020123456A1`, `wo 2020/123456`,
   `WO-2020-123456` or `WO 2020/123456 A1`.
2. The client decides which *server* lookup runs: `apps/web/src/state/url.ts`
   `looksLikePublicationNumber` (`/^[A-Z]{2}\d{5,12}[A-Z]\d?$/`) is stricter than the
   data, so `wo 2020/123456` is not even sent to the patent endpoint — it is routed to
   the natural-language planner, which then answers "unresolved" for it. The
   server-side planner has the same strict rule (`planner._PUBNUM_RE`).

## 2. What is deliberately *not* changed

- **The stored value is never rewritten.** The corpus row keeps the identifier the
  source published; the answer says which stored identifier answered the question.
  (AGENTS.md §10, §11.)
- **A genuine miss stays a miss.** `WO9999999999A1` is still not found; the tolerant
  path cannot invent a family.
- **Free text is not turned into an identifier.** The tolerant rule is a deterministic
  *shape*, not language interpretation (AGENTS.md §12 keeps `LLM_INFERRED` out of
  identifier parsing): a string needs a country code and at least six digits, and it
  must be the **whole** query. Prose goes to the planner exactly as before.
- **The corpus coverage check stays exact.** `publications_in_corpus` (B-01) answers
  "was *this* number imported?", and an operator's coverage report must not be
  softened by normalization. The tolerance belongs to the interactive lookup.
- **No schema change, no second normalization implementation, no new service.** The
  tolerant path runs only after the indexed exact lookup misses.

## 3. Design

**One shape rule, three consumers** (`spago_core/domain/patent_numbers.py`):

```python
MATCH_RULE = "publication-number-tolerant-v1"

def looks_like_publication_number(value: object) -> bool:
    """The *whole* string is one publication number, in any form people write."""
```

Implementation: strip separator punctuation (space, hyphen, slash, period, comma),
uppercase, then match `^[A-Z]{2}\d{6,13}(?:[A-Z]\d?)?$` — country code, 6–13 digits, an
optional kind code (`EP1234567` is a publication number too; only a body shorter than
six digits is refused, because inventing a patent number is worse than missing one).
Consumers:

| Consumer | Change |
| --- | --- |
| `services/core.py::find_patent` | exact lookup first, then the tolerant match |
| `services/planner.py` | `OpenPatentStep` validation and the offline token parse ask this function instead of `_PUBNUM_RE` (which stays as the documented pattern, now expressed once) |
| `apps/web/src/state/url.ts` | the mirrored TS rule, kept identical by a parity test |

**Lookup** (`find_patent`, return type becomes `PatentLookup`):

1. exact `publication_number = :pn` → `exact=True`, cost unchanged;
2. else normalize the request with `patent_tokens` (the same lenient extractor the
   source paths use, so `wo 2020/123456` → `WO2020123456`); no token → `NotFoundError`
   that says the query carries no publication number;
3. scan `patent_documents` (`id, family_id, publication_number` only), keep rows whose
   normalized tokens intersect the request, and count **distinct stored identifiers**:
   - one → answer it, `matched=<stored>`, `exact=False`, `rule=MATCH_RULE`;
   - more than one → `AmbiguousError` listing every stored identifier (409). A
     granted patent stored as both `US-8618102-B1` and `US8618102B2` is a real corpus
     state and is *reported*, never guessed;
   - none → `NotFoundError` (404), unchanged in meaning.

**API.** `PatentResponse` gains `match: {requested, matched, exact, rule}`. A new
`AmbiguousError` maps to 409 with a message that names the candidates and says to open
one by its stored number; the client's existing `detail` handling shows it.

**UI.** One small note next to the table heading when `exact` is false:
`matched WO-2020-123456-A · normalized from “wo 2020/123456”`, with the rule as its
tooltip. No new panel, no second control (§17/§18); the typed query stays in the URL
and in the page title (§19).

## 4. Verification

- Unit cases in `services/core/tests/test_b03_tolerant_lookup.py`: separator, case,
  slash-form, kind-code-present/absent, comma-grouped, too-few-digits, prose, two
  numbers, empty, `DEMO-PATENT-A` (must not be read as a publication number).
- PG integration: exact hit unchanged; tolerant hit reports the stored identifier and
  leaves the row untouched; a document stored in WIPO split form is found by the
  unified form; a genuine miss is 404; two normalized-equal stored documents are 409
  with both named; free text is 404.
- Parity test: the TS regex in `apps/web/src/state/url.ts` equals the Python pattern.
- Browser: type `wo 2020/123456` for a seeded stored `WO-2020-123456-A`, see the family
  open with the match note; reload the deep link; a genuine miss still shows the 404
  state.
- Measurement: the tolerant scan over a synthetic 50 000-document corpus
  (`benchmarks/tolerant-lookup-2026-09-16.md`), recorded as the cost of the decision
  in §3, with the exact path re-measured beside it.
- Full suite + `npm run build`; `rtk git diff --check`.

## 5. Result

**Implemented 2026-09-16.**

- `domain/patent_numbers.py`: `MATCH_RULE` (`publication-number-tolerant-v1`) and
  `looks_like_publication_number`. The rule is one pattern
  (`_QUERY_RE = ^[A-Z]{2}\d{6,13}(?:[A-Z]\d?)?$` over a separator-stripped, uppercased
  string) with the client's TS literal and the Python source kept in step by a parity
  test, because a comment claiming two rules are the same is not a check.
- `services/core.py`: `PatentLookup` (`document`, `overview`, `requested`, `matched`,
  `exact`, `rule`) replaces the two-tuple; `find_patent` does the exact indexed lookup
  first and only then the tolerant scan, which reads `id, family_id,
  publication_number` and verifies with the same `patent_tokens` the source paths use.
  `AmbiguousError` is raised when more than one stored identifier answers — the
  identifiers are listed in the message, never picked between.
- `api/routes.py`: `PatentMatch` in the response, 409 for ambiguity; the 404 messages
  now distinguish "carries no publication number" from "not in this dataset".
- `planner.py`: `OpenPatentStep` and the offline token parse call the shared rule, so
  the same text behaves the same in the search box and in the plan.
- `plan_execution.py`: the step detail names the stored identifier when the match was
  normalized, so a plan transcript cannot silently disagree with the corpus.
- Frontend: `PatentMatch` in `types.ts`, the tolerant client rule, and one note in the
  table heading (`match-note`) that appears only when the match was normalized;
  export filenames for a declared-compound download are sanitized now that a slash can
  reach them.
- Tests: `services/core/tests/test_b03_tolerant_lookup.py` (48 cases: shape unit
  tests, the parity check, PG lookup/404/409/plan paths) — the suite went from 595 to
  643 (`643 passed in 142.36s`, run from the current checkout; the number is collected
  with `pytest --collect-only -q`, because `addopts = "-q"` hides pytest's own summary
  line).

**Verified:**

- Backend: 643 passed, 0 failed (full suite, local stack running).
- `npm run build` clean; `npx tsc --noEmit` clean.
- Live browser check on the local stack (already-built assets served by the API
  container at `localhost:8000`), four cases:
  1. `?q=WO-2020-123456-A` (stored verbatim) → family opens, **no** match note, i.e. the
     exact path is still exact;
  2. `?q=wo 2020/123456` → the request travels as `/patents/WO2020123456` (a "/" cannot
     be a path segment), the family opens with `matched WO-2020-123456-A for “wo
     2020/123456”`, and the declared-compound strip below it reads the *stored* number;
  3. `?q=wo 2020/999999` → 404 state plus the declared panel, and asking ChEMBL on the
     slash form stores and displays `empty` with its match rule;
  4. `?q=US 10,508,115` → 404 state plus the declared panel showing the live stored set
     (`134 records for 73 compounds`, `documents matched US-10508115-B2`, rejection
     counts and the rule), reached from a spelling no source stores.
- `benchmarks/tolerant-lookup-2026-09-16.md`: the scan over 50 000 synthetic documents
  costs 155 ms (exact path 1.35 ms, unchanged), with the read/comparison split.

**Found while verifying (fixed in this round, recorded because a unit test could not
see it):** the declared-compound panel (`SourceDeclaredCompounds.tsx`, B-24) decided
whether an answer belonged to the panel it was rendered in by comparing
`requested_number` with the prop **as strings**. For a slash form the request travels
canonicalized (case 2 above), so the stored `requested_number` came back
`WO2020123456` while the prop was `wo 2020/123456`: a *successful* lookup was discarded
and the panel kept saying "nothing asked" over a set that existed. Fixed by comparing
the canonical forms on both sides (`canonicalPublicationNumber`, the mirrored rule) and
by keying the panel's query cache on the canonical number, so one publication has one
cache entry however it is typed. Re-verified in the browser (cases 2 and 3): the fresh
answer lands, and the stored read for the canonical number is what a later visit sees.
The lesson is the B-24 one repeated on the other side: identity through the API has to
be one thing, and a string comparison at the edge is where it breaks.

**Not done / limits:** a corpus holding two documents whose identifiers normalize to
one token still cannot be opened by that ambiguous form (409 by design, with the
candidates named); the note is information, not a picker. A dedicated candidate picker
for the ambiguous case is recorded in the backlog as `LATER` rather than built here
(§17, §38). The tolerant scan is measured only up to 50 000 documents; the artifact
states the linear scaling and the corpus size at which the design has to be revisited.
