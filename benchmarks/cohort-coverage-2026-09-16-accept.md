# Cohort coverage matrix

Generated 2026-09-16T05:23:38+00:00 from the running build (`api_version` 0.1.0).
Produced by `scripts/cohort_coverage.py` through the shipped read paths (`coverage_matrix`, `reference_verdicts`), not by hand.

Requested cohort: TSLP, CD40LG, IL-6, IL-6R, EGFR

## TSLP — Thymic stromal lymphopoietin

UniProt Q969D9 · single_protein · Homo sapiens

| Source | Status | Seen | Kept | Excluded | Candidates | Small-molecule | Version |
| --- | --- | --- | --- | --- | --- | --- | --- |
| bindingdb | complete | 3 | 3 | 0 | 3 | 0 | bindingdb:2026-09-16 |
| chembl | complete | 114 | 111 | 3 | 69 | 1 | chembl:2026-09-16 |
| pubchem | complete | 20 | 0 | 0 | 0 | 0 | pubchem-pug-rest |

Verdict: **does not qualify** — Only 53 compound(s) outside the modality scope are at or below 10 µM; no in-scope compound is.

0 of 1 in-scope compound(s) at or below 10 µM under `potency-gate-v1` (scope: small molecules and unclassified entities); 0 above it, 0 undecided, 1 not a potency; 1 in-scope record(s), 0 value(s) without a structure.

## CD40LG — CD40 ligand

UniProt P29965 · single_protein · Homo sapiens

| Source | Status | Seen | Kept | Excluded | Candidates | Small-molecule | Version |
| --- | --- | --- | --- | --- | --- | --- | --- |
| bindingdb | empty | 0 | 0 | 0 | 0 | 0 | bindingdb:2026-09-16 |
| chembl | complete | 46 | 21 | 25 | 11 | 10 | chembl:2026-09-16 |
| pubchem | complete | 22 | 0 | 0 | 0 | 0 | pubchem-pug-rest |

Verdict: **qualifies** — 6 of 10 in-scope compound(s) at or below 10 µM; the retrieved set can serve as a potency reference for this target.

6 of 10 in-scope compound(s) at or below 10 µM under `potency-gate-v1` (scope: small molecules and unclassified entities); 3 above it, 0 undecided, 1 not a potency; 20 in-scope record(s), 0 value(s) without a structure.

## IL-6

**Not in the stored matrix** — not stored. A target with no stored retrieval has no coverage to report; this is not a zero result.

## IL-6R

**Not in the stored matrix** — not stored. A target with no stored retrieval has no coverage to report; this is not a zero result.

## EGFR — Epidermal growth factor receptor

UniProt P00533 · single_protein · Homo sapiens

| Source | Status | Seen | Kept | Excluded | Candidates | Small-molecule | Version |
| --- | --- | --- | --- | --- | --- | --- | --- |
| bindingdb | complete | 974 | 974 | 0 | 946 | 932 | bindingdb:2026-09-16 |
| chembl | partial | 2598 | 2397 | 200 | 1639 | 1635 | chembl:2026-09-16 |
| pubchem | partial | 4609 | 0 | 0 | 0 | 0 | pubchem-pug-rest |

Verdict: **qualifies** — 1833 of 2531 in-scope compound(s) at or below 10 µM; the retrieved set can serve as a potency reference for this target.

1833 of 2531 in-scope compound(s) at or below 10 µM under `potency-gate-v1` (scope: small molecules and unclassified entities); 516 above it, 44 undecided, 138 not a potency; 3328 in-scope record(s), 0 value(s) without a structure.

---

A `failed` row is a source outage; an `empty` row is a source that answered
with nothing; a target absent from this matrix was never investigated. The
three are different facts and are not collapsed here.
