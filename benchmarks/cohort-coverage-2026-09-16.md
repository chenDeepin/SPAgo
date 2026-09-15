# Cohort coverage matrix

Generated 2026-09-15T18:59:23+00:00 from the running build (`api_version` 0.1.0).
Produced by `scripts/cohort_coverage.py` through the shipped read paths (`coverage_matrix`, `reference_verdicts`), not by hand.

Requested cohort: TSLP, CD40LG, **P05231 (IL-6)**, **P08887 (IL-6R)**, EGFR.

The two accessions are named because their gene symbols resolve **ambiguously**
(see "Resolution is part of the result" below); the accessions are what was
investigated. Raw record: `cohort-coverage-2026-09-16.json`.

## TSLP — Thymic stromal lymphopoietin

UniProt Q969D9 · single_protein · Homo sapiens

| Source | Status | Seen | Kept | Excluded | Candidates | Small-molecule | Version |
| --- | --- | --- | --- | --- | --- | --- | --- |
| bindingdb | complete | 3 | 3 | 0 | 3 | 0 | bindingdb:2026-09-15 |
| chembl | complete | 114 | 111 | 3 | 69 | 1 | chembl:2026-09-15 |
| pubchem | complete | 20 | 0 | 0 | 0 | 0 | pubchem-pug-rest |

Verdict: **qualifies** — 1 of 2 in-scope compound(s) at or below 10 µM; the retrieved set can serve as a potency reference for this target. 1 hand-added row(s) were withdrawn by the user and are not counted.

1 of 2 in-scope compound(s) at or below 10 µM under `potency-gate-v1` (scope: small molecules and unclassified entities); 0 above it, 0 undecided, 1 not a potency; 2 in-scope record(s), 0 value(s) without a structure.

## CD40LG — CD40 ligand

UniProt P29965 · single_protein · Homo sapiens

| Source | Status | Seen | Kept | Excluded | Candidates | Small-molecule | Version |
| --- | --- | --- | --- | --- | --- | --- | --- |
| bindingdb | empty | 0 | 0 | 0 | 0 | 0 | bindingdb:2026-09-15 |
| chembl | complete | 46 | 21 | 25 | 11 | 10 | chembl:2026-09-15 |
| pubchem | complete | 22 | 0 | 0 | 0 | 0 | pubchem-pug-rest |

Verdict: **qualifies** — 6 of 10 in-scope compound(s) at or below 10 µM; the retrieved set can serve as a potency reference for this target.

6 of 10 in-scope compound(s) at or below 10 µM under `potency-gate-v1` (scope: small molecules and unclassified entities); 3 above it, 0 undecided, 1 not a potency; 20 in-scope record(s), 0 value(s) without a structure.

## IL6 — Interleukin-6

UniProt P05231 · single_protein · Homo sapiens

| Source | Status | Seen | Kept | Excluded | Candidates | Small-molecule | Version |
| --- | --- | --- | --- | --- | --- | --- | --- |
| bindingdb | complete | 9 | 9 | 0 | 9 | 9 | bindingdb:2026-09-15 |
| chembl | complete | 412 | 166 | 246 | 144 | 144 | chembl:2026-09-15 |
| pubchem | partial | 48 | 0 | 0 | 0 | 0 | pubchem-pug-rest |

Verdict: **qualifies** — 124 of 144 in-scope compound(s) at or below 10 µM; the retrieved set can serve as a potency reference for this target.

124 of 144 in-scope compound(s) at or below 10 µM under `potency-gate-v1` (scope: small molecules and unclassified entities); 3 above it, 1 undecided, 16 not a potency; 175 in-scope record(s), 0 value(s) without a structure.

## IL6R — Interleukin-6 receptor subunit alpha

UniProt P08887 · single_protein · Homo sapiens

| Source | Status | Seen | Kept | Excluded | Candidates | Small-molecule | Version |
| --- | --- | --- | --- | --- | --- | --- | --- |
| bindingdb | failed | 0 | 0 | 0 | 0 | 0 | bindingdb:2026-09-15 |
| chembl | complete | 5 | 1 | 4 | 1 | 1 | chembl:2026-09-15 |
| pubchem | complete | 17 | 0 | 0 | 0 | 0 | pubchem-pug-rest |

Verdict: **does not qualify** — 1 compound(s) have 1 record(s) that are not potency measurements (kinetic, percent or non-concentration units); none of them can be compared with 10 µM.

0 of 1 in-scope compound(s) at or below 10 µM under `potency-gate-v1` (scope: small molecules and unclassified entities); 0 above it, 0 undecided, 1 not a potency; 1 in-scope record(s), 0 value(s) without a structure.

## EGFR — Epidermal growth factor receptor

UniProt P00533 · single_protein · Homo sapiens

| Source | Status | Seen | Kept | Excluded | Candidates | Small-molecule | Version |
| --- | --- | --- | --- | --- | --- | --- | --- |
| bindingdb | complete | 974 | 974 | 0 | 946 | 932 | bindingdb:2026-09-15 |
| chembl | partial | 2598 | 2397 | 200 | 1639 | 1635 | chembl:2026-09-15 |
| pubchem | partial | 4609 | 0 | 0 | 0 | 0 | pubchem-pug-rest |

Verdict: **qualifies** — 1833 of 2531 in-scope compound(s) at or below 10 µM; the retrieved set can serve as a potency reference for this target.

1833 of 2531 in-scope compound(s) at or below 10 µM under `potency-gate-v1` (scope: small molecules and unclassified entities); 516 above it, 44 undecided, 138 not a potency; 3328 in-scope record(s), 0 value(s) without a structure.

## Reading this matrix

The acceptance cohort, re-measured on this build. Two of the five queries had to be
investigated by **accession**, not by gene symbol:

### Resolution is part of the result

`IL-6` and `IL-6R` did not resolve to a single UniProt entry — the resolution
reported `ambiguous` and *stored nothing*, which is the designed behaviour
(alternatives are recorded, never silently chosen, `AGENTS.md` §12). The matrix is
therefore reported for `P05231` (IL-6) and `P08887` (IL-6R). An invited user typing
"IL-6" meets the same choice; the script in `docs/online-capability.md` §6 should be
read as "resolve the requested target and read which entry was selected", and an
ambiguous symbol is a step to record, not a failure.

### What changed since the 2026-09-15 coverage record

| Target | 2026-09-15 | this run | note |
| --- | --- | --- | --- |
| TSLP | 1 small-molecule candidate, 111 ChEMBL kept | 1 small molecule, 2 in-scope, 1 at/below 10 µM | unchanged; peptides still dominate 111 kept |
| CD40LG | 10 small-molecule candidates, BindingDB empty | 10 small molecules of 11 candidates, **6 at/below 10 µM → qualifies** | the set is small but it is a *usable* reference set; the earlier "thin" label said less than the policy does |
| IL-6 | 144 small-molecule candidates | 144 small molecules, **124 at/below 10 µM → qualifies**, 175 in-scope records | unchanged coverage, and the verdict is now stated |
| IL-6R | 1 candidate, BindingDB failed | 1 candidate, its only record is **not a potency**; BindingDB **failed** again | the thinnest target in the cohort, with a live source failure |
| EGFR (control) | 2531 small-molecule candidates | 2531 in-scope, 1833 at/below 10 µM, ChEMBL **partial** (bound reached) | the positive control still returns a large set, so a thin acceptance target is a coverage fact, not a broken adapter |

Two corrections follow from this and are applied to `docs/online-capability.md` §5:
"IL-6R **and CD40LG** are thin" was wrong about CD40LG — 10 in-scope compounds with 6
at or below the threshold is a qualifying reference set under `potency-gate-v1`.
IL-6R stays thin, and its BindingDB failure is a source outage that must not be read
as "no measurements exist" (the retrieval's own warning says so).

### What this matrix does not say

- It is the **open-database** coverage for these five targets on this dataset
  version, not a statement about the literature, and not an inhibitor count.
- `pubchem` rows with `seen > 0, kept = 0` are screening-assay *context*; PubChem
  contributes no measurements by design, so a zero there is not a coverage gap.
- A `partial` ChEMBL row for EGFR means the 2,000-activity bound was reached — more
  records exist upstream than were retrieved.
- Counting rules are the shipped policy; a different `SPAGO_ACTIVITY_THRESHOLD_NM`
  would move the "at or below" column and cannot change the retrieval counts.

## How this was produced

```bash
# populated the two targets that had never been investigated (live upstream)
docker compose run --rm -v "$PWD/scripts:/app/scripts:ro" app \
    python /app/scripts/cohort_coverage.py P05231 P08887 --investigate --yes
# re-recorded the matrix for the cohort
docker compose run --rm -v "$PWD/scripts:/app/scripts:ro" app \
    python /app/scripts/cohort_coverage.py TSLP CD40LG P05231 P08887 EGFR --json --out -
```

TSLP and CD40LG were re-investigated through the same tool (bounded retrieval, live
sources) before the read; their counts above are from that retrieval, not from the
earlier record.

---

A `failed` row is a source outage; an `empty` row is a source that answered
with nothing; a target absent from this matrix was never investigated. The
three are different facts and are not collapsed here.

