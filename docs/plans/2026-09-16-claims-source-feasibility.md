# B-21 — Claim-text source feasibility and evidence design (prepared decision)

Date: 2026-09-16 · Register: `docs/plans/backlog.md` B-21 · Class NEXT (decision
deliverable) · Status: **feasibility prepared; the source/terms decision is the
operator's** (OPS registration, credentials, terms acceptance).

Planning review 2026-09-17: this is a prepared decision dossier, not a prerequisite
for a pilot that retains the existing “claims were not assessed” limit. See the
[pilot acceptance plan](2026-09-17-pilot-acceptance-plan.md). No external source or
terms were rechecked in this review; the dated observations below must be verified
before adopting a source or planning paid use.

## Vision alignment

`PROMPT.md` §2.1 makes claims a product pillar, and every summary today states
"claims were not assessed" — the largest remaining gap between the product
story and the shipped workflow. This document is the item's first deliverable:
the source/terms evidence a decision needs, the evidence mapping, and
success/failure criteria. **It does not enable claims UI**, and no source was
chosen.

## What each candidate source actually offers for claim text

### EPO OPS (claim-text candidate in this comparison)

- Endpoint: `GET /rest-services/published-data/publication/epo/{number}/claims`
  (OPS 3.2), plus `fulltext` variants and a two-step availability inquiry the
  EPO itself recommends (biblio/fulltext inquiry reports whether claims text
  exists for a document before it is fetched). XML/JSON; per-claim numbering is
  part of the document structure.
- Access: OAuth2 consumer key/secret from the EPO Developer Portal; SPAgo's
  existing bounded-adapter rules (§16: timeout, retry-where-safe, cache, rate
  limit, source identity) would apply unchanged.
- Terms (fair-use charter, checked 2026-09-16): ≈1 Mbit/s traffic cap,
  individual-IP search threshold 10 actions/minute, free registered tier
  ≈3.5–4 GB served data/week with green/yellow/red quota bands surfaced in
  response headers and HTTP 403 on exhaustion; commercial volumes purchasable.
  Attribution/quota duties would be recorded in `THIRD_PARTY_NOTICES.md` (§23
  data-terms row) if adopted.
- Honest limits: claims text availability varies by publishing authority and
  language; a `claims` answer can be absent for a document that exists. The
  adapter must report availability as a first-class state, never as empty
  claims.

### SureChEMBL bulk (section annotation, not claim text)

- The bulk release carries compounds, patent documents, and compound–patent
  relationship files; documents have title/abstract/description/claims
  sections, and relationships track where a compound appears.
- **The pipeline does not distinguish claimed from merely mentioned
  compounds** (SureChEMBL's own 2021 core-structure work and ChEMBL blog
  confirm this), and claim *text* is not a bulk field. A "found in the claims
  section" occurrence annotation is derivable; it is not claim text and must
  never be presented as such (§10).

**Preliminary conclusion within the two paths compared here (for the operator to
accept or reject):** OPS is the claim-text candidate; this is not an exhaustive
survey or a claim that no other authoritative source exists.
SureChEMBL can at most corroborate that a compound occurs in the claims
section. They answer different questions and are not substitutes.

## Evidence mapping (applies to whichever source is chosen)

Claims land in the existing typed evidence model, not a new one: one
`evidence_records` row per claim (or claim paragraph, if the sample shows
per-claim rows are too coarse), with `source_type='claim'`, the claim number in
`compound_local_id`-style locator fields extended with claim number +
paragraph, `section='claims'`, jurisdiction from the document, language
recorded when not English, `extraction_method='ops_claims'` (or the chosen
source's token) and `provenance_state='source_fact'`. The document summary's
existing `claims_assessed` flag (count of claim-typed records) then flips from
zero without any UI redesign. The legal boundary (§32) is restated in the
claims surface: claim text is a source fact, not a scope opinion.

## Bounded sample design (runs only after credentials exist)

1. Cohort: a bounded list of actual publication numbers from selected real-data
   acceptance families and stored investigations' declared patents (US/EP/WO mix,
   tens rather than hundreds). Exclude synthetic `DEMO-*` documents from live
   requests and the coverage denominator. Record the exact list before querying;
   synthetic claims fixtures may test parsing separately, not source availability.
2. Per document: availability inquiry, then claims fetch; record claim count,
   language(s), per-claim paragraph counts, bytes, latency, and the quota-band
   headers consumed.
3. Proposed success target, to review with the sample: ≥90 % of its documents return
   usable claims text, with results also broken down by authority/language. Per-claim
   identifiers parse deterministically and the original numbered claim is locatable
   from the evidence inspector. Fetching claim text does not establish a mapping from
   a compound example to a claim or determine claim scope; such assertions need their
   own evidence and remain outside this feasibility step.
4. Failure criteria (any kills the integration, recorded as the negative
   result): per-claim identity is not recoverable from the response structure;
   the free-tier quota cannot cover the cohort's refresh cadence at the
   operator's chosen interval; terms forbid the retention pattern the evidence
   model needs.

## What this document does not do

No source was selected, no credentials requested, no adapter written, and no
claims UI exists. B-22 (the OPS adapter itself) stays P3 behind this decision.
The sample cannot run until the operator registers with the EPO Developer
Portal and accepts the fair-use terms — that is the gate this deliverable
names, per the item's own contract.

Sources consulted 2026-09-16: EPO OPS pages and fair-use charter
(epo.org/searching-for-patents/data/web-services/ops;
epo.org/service-support/ordering/fair-use), SureChEMBL bulk-data documentation
(chembl.gitbook.io/surechembl/downloads/bulk-data), the SureChEMBL 2.0 release
notes (EMBL-EBI; ChEMBL blog, May 2025), "Exploring SureChEMBL from a drug
discovery perspective" (Sci Data 2024), and the JCIM 2021 core-structure paper
on claimed-vs-mentioned compounds.
