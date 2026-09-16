# Cohort review pack (B-32, machine half)

Generated 2026-09-16T15:35:35+00:00 by `scripts/cohort_pack.py` (generator checkout `eb486d0-dirty`, spago_core `0.1.0`). Raw record: `benchmarks/cohort-pack-2026-09-16.json`.

## Served build

Fetched verbatim from `http://127.0.0.1:8000/healthz`:

- build_id `d9f441a-dirty` (build_source: env)
- api_version 0.1.0 · dataset_version demo-fixture-v1 · status ok
- expected: `d9f441a-dirty` · match: **yes**

## Schema

20 migration(s) applied (0001_init.sql … 0020_measurement_retraction.sql); pending in the generator's checkout: none.

## Policy and bounds

`potency-gate-v1`: threshold 10 µM, minimum 10 compound(s), scope small molecules and unclassified entities. Verdict read cap 5000 rows per target. Retrieval defaults if a target were re-investigated: chembl_max_activities_per_target_id=2000, chembl_max_molecule_lookups=25, pubchem_max_assay_ids=25, http_max_attempts=3, http_timeout_s=25.0. Stored rows carry the bounds of their own retrieval time in each source row's `query` and `warnings`.

## Targets

Requested cohort: TSLP, CD40LG, P05231, P08887, EGFR

### TSLP

TSLP — Thymic stromal lymphopoietin · UniProt Q969D9 · single_protein · Homo sapiens (resolved via uniprot uniprot:2026-09-15)

| Source | Status | Seen | Kept | Excluded | Candidates | Small-molecule | Version | Retrieved |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| bindingdb | complete | 3 | 3 | 0 | 3 | 0 | bindingdb:2026-09-15 | 2026-09-15T18:55:35.915205+00:00 |
| chembl | complete | 114 | 111 | 3 | 69 | 1 | chembl:2026-09-15 | 2026-09-15T18:55:35.172239+00:00 |
| pubchem | complete | 20 | 0 | 0 | 0 | 0 | pubchem-pug-rest | 2026-09-15T18:55:36.673687+00:00 |

Verdict (source-only): **does not qualify** — Only 53 compound(s) outside the modality scope are at or below 10 µM; no in-scope compound is.

0 of 1 in-scope compound(s) at or below 10 µM under `potency-gate-v1` (scope: small molecules and unclassified entities); 0 above it, 0 undecided, 1 not a potency; 1 in-scope record(s), 0 value(s) without a structure; 53 active(s) outside the modality scope.

Verdict (combined workspace): **qualifies** — 1 of 2 in-scope compound(s) at or below 10 µM; the retrieved set can serve as a potency reference for this target. 1 hand-added row(s) were withdrawn by the user and are not counted.

1 of 2 in-scope compound(s) at or below 10 µM under `potency-gate-v1` (scope: small molecules and unclassified entities); 0 above it, 0 undecided, 1 not a potency; 2 in-scope record(s), 0 value(s) without a structure; 53 active(s) outside the modality scope.

Stratification (115 record(s) in the read, 2 inside the policy scope): evidence {"measured_direct_binding": 59, "functional_effect": 55, "unspecified": 1}; censor relation {"=": 113, ">": 2}; class {"not_applicable": 59, "active": 54, "unknown": 1, "weak": 1}; 1 supplement record(s); stereo stored (SMILES + InChIKey) for 115 of 115; 0 record(s) name a source-declared patent (none) while 1 occur in a stored corpus document — declared and occurring are counted separately, never merged.

### CD40LG

CD40LG — CD40 ligand · UniProt P29965 · single_protein · Homo sapiens (resolved via uniprot uniprot:2026-09-15)

| Source | Status | Seen | Kept | Excluded | Candidates | Small-molecule | Version | Retrieved |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| bindingdb | empty | 0 | 0 | 0 | 0 | 0 | bindingdb:2026-09-15 | 2026-09-15T18:55:43.642288+00:00 |
| chembl | complete | 46 | 21 | 25 | 11 | 10 | chembl:2026-09-15 | 2026-09-15T18:55:42.921198+00:00 |
| pubchem | complete | 22 | 0 | 0 | 0 | 0 | pubchem-pug-rest | 2026-09-15T18:55:45.083576+00:00 |

Verdict (source-only): **qualifies** — 6 of 10 in-scope compound(s) at or below 10 µM; the retrieved set can serve as a potency reference for this target.

6 of 10 in-scope compound(s) at or below 10 µM under `potency-gate-v1` (scope: small molecules and unclassified entities); 3 above it, 0 undecided, 1 not a potency; 20 in-scope record(s), 0 value(s) without a structure.

Verdict (combined workspace): **qualifies** — 6 of 10 in-scope compound(s) at or below 10 µM; the retrieved set can serve as a potency reference for this target.

6 of 10 in-scope compound(s) at or below 10 µM under `potency-gate-v1` (scope: small molecules and unclassified entities); 3 above it, 0 undecided, 1 not a potency; 20 in-scope record(s), 0 value(s) without a structure.

Stratification (21 record(s) in the read, 20 inside the policy scope): evidence {"interaction_disruption": 16, "unspecified": 4, "measured_direct_binding": 1}; censor relation {"=": 20, ">": 1}; class {"weak": 9, "active": 8, "not_applicable": 4}; 0 supplement record(s); stereo stored (SMILES + InChIKey) for 21 of 21; 0 record(s) name a source-declared patent (none) while 0 occur in a stored corpus document — declared and occurring are counted separately, never merged.

### P05231

IL6 — Interleukin-6 · UniProt P05231 · single_protein · Homo sapiens (resolved via uniprot uniprot:2026-09-15)

| Source | Status | Seen | Kept | Excluded | Candidates | Small-molecule | Version | Retrieved |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| bindingdb | complete | 9 | 9 | 0 | 9 | 9 | bindingdb:2026-09-16 | 2026-09-16T14:31:15.103513+00:00 |
| chembl | complete | 412 | 166 | 246 | 144 | 144 | chembl:2026-09-16 | 2026-09-16T14:31:14.356362+00:00 |
| pubchem | partial | 48 | 0 | 0 | 0 | 0 | pubchem-pug-rest | 2026-09-16T14:31:15.821084+00:00 |

Verdict (source-only): **qualifies** — 135 of 157 in-scope compound(s) at or below 10 µM; the retrieved set can serve as a potency reference for this target.

135 of 157 in-scope compound(s) at or below 10 µM under `potency-gate-v1` (scope: small molecules and unclassified entities); 5 above it, 1 undecided, 16 not a potency; 328 in-scope record(s), 0 value(s) without a structure.

Verdict (combined workspace): **qualifies** — 135 of 157 in-scope compound(s) at or below 10 µM; the retrieved set can serve as a potency reference for this target.

135 of 157 in-scope compound(s) at or below 10 µM under `potency-gate-v1` (scope: small molecules and unclassified entities); 5 above it, 1 undecided, 16 not a potency; 328 in-scope record(s), 0 value(s) without a structure.

Stratification (328 record(s) in the read, 328 inside the policy scope): evidence {"measured_direct_binding": 198, "functional_effect": 130}; censor relation {"=": 320, "<": 4, ">": 4}; class {"active": 301, "not_applicable": 18, "weak": 7, "unknown": 2}; 0 supplement record(s); stereo stored (SMILES + InChIKey) for 328 of 328; 277 record(s) name a source-declared patent (US10189796, US10435379, US10457681, US10487084, US10508115, US10919895, US10981914, US8901310, US9694015) while 0 occur in a stored corpus document — declared and occurring are counted separately, never merged.

### P08887

IL6R — Interleukin-6 receptor subunit alpha · UniProt P08887 · single_protein · Homo sapiens (resolved via uniprot uniprot:2026-09-15)

| Source | Status | Seen | Kept | Excluded | Candidates | Small-molecule | Version | Retrieved |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| bindingdb | failed | 0 | 0 | 0 | 0 | 0 | bindingdb:2026-09-15 | 2026-09-16T10:36:42.803755+00:00 |
| chembl | complete | 5 | 1 | 4 | 1 | 1 | chembl:2026-09-15 | 2026-09-15T18:58:49.294219+00:00 |
| pubchem | complete | 17 | 0 | 0 | 0 | 0 | pubchem-pug-rest | 2026-09-15T18:58:51.127416+00:00 |

Verdict (source-only): **does not qualify** — 1 compound(s) have 1 record(s) that are not potency measurements (kinetic, percent or non-concentration units); none of them can be compared with 10 µM.

0 of 1 in-scope compound(s) at or below 10 µM under `potency-gate-v1` (scope: small molecules and unclassified entities); 0 above it, 0 undecided, 1 not a potency; 1 in-scope record(s), 0 value(s) without a structure.

Verdict (combined workspace): **does not qualify** — 1 compound(s) have 1 record(s) that are not potency measurements (kinetic, percent or non-concentration units); none of them can be compared with 10 µM.

0 of 1 in-scope compound(s) at or below 10 µM under `potency-gate-v1` (scope: small molecules and unclassified entities); 0 above it, 0 undecided, 1 not a potency; 1 in-scope record(s), 0 value(s) without a structure.

Stratification (1 record(s) in the read, 1 inside the policy scope): evidence {"functional_effect": 1}; censor relation {"=": 1}; class {"not_applicable": 1}; 0 supplement record(s); stereo stored (SMILES + InChIKey) for 1 of 1; 0 record(s) name a source-declared patent (none) while 0 occur in a stored corpus document — declared and occurring are counted separately, never merged.

### EGFR

EGFR — Epidermal growth factor receptor · UniProt P00533 · single_protein · Homo sapiens (resolved via uniprot uniprot:2026-09-15)

| Source | Status | Seen | Kept | Excluded | Candidates | Small-molecule | Version | Retrieved |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| bindingdb | complete | 974 | 974 | 0 | 946 | 932 | bindingdb:2026-09-15 | 2026-09-15T18:56:54.601585+00:00 |
| chembl | partial | 2598 | 2397 | 200 | 1639 | 1635 | chembl:2026-09-15 | 2026-09-15T18:56:40.603182+00:00 |
| pubchem | partial | 4609 | 0 | 0 | 0 | 0 | pubchem-pug-rest | 2026-09-15T18:56:55.706898+00:00 |

Verdict (source-only): **qualifies** — 1833 of 2531 in-scope compound(s) at or below 10 µM; the retrieved set can serve as a potency reference for this target.

1833 of 2531 in-scope compound(s) at or below 10 µM under `potency-gate-v1` (scope: small molecules and unclassified entities); 516 above it, 44 undecided, 138 not a potency; 3328 in-scope record(s), 0 value(s) without a structure; 15 active(s) outside the modality scope.

Verdict (combined workspace): **qualifies** — 1833 of 2531 in-scope compound(s) at or below 10 µM; the retrieved set can serve as a potency reference for this target.

1833 of 2531 in-scope compound(s) at or below 10 µM under `potency-gate-v1` (scope: small molecules and unclassified entities); 516 above it, 44 undecided, 138 not a potency; 3328 in-scope record(s), 0 value(s) without a structure; 15 active(s) outside the modality scope.

Stratification (3346 record(s) in the read, 3328 inside the policy scope): evidence {"measured_direct_binding": 2818, "interaction_disruption": 304, "functional_effect": 118, "unspecified": 106}; censor relation {"=": 2671, ">": 526, "<": 147, "~": 2}; class {"active": 2300, "weak": 705, "not_applicable": 287, "unknown": 54}; 0 supplement record(s); stereo stored (SMILES + InChIKey) for 3346 of 3346; 0 record(s) name a source-declared patent (none) while 0 occur in a stored corpus document — declared and occurring are counted separately, never merged.

## Limits

- This pack was prepared by a machine (`scripts/cohort_pack.py`) from stored rows and served metadata. A machine can prepare a review but cannot approve one: the independent human cross-read (B-32's gated half, feeding B-31) is not performed or recorded here, and nothing in this file may be read as its result.
- Every number describes this stored workspace only. A different stored workspace (for example the isolated `*-accept` rehearsal) holds different rows and can carry a different verdict; that is different data, not a conflicting measurement.
- The verdicts were recomputed by the generator checkout (identity below) from the stack's stored rows through the shipped service functions; the served build identity is what `/healthz` reported. When the two differ, the pack names both instead of blending them.
- The source-only verdict excludes hand-added rows (`user_supplement`); the combined verdict includes them. Unconfirmed proposals and withdrawn rows are outside both counts and stay visible in the combined verdict's own fields.
- No source was called and nothing was written: the pack is a read. A licensed snapshot (B-23) is an operator access path with no leg in this pack, so nothing here is a snapshot scan of any publication.
- Records that carried a value but no drawable structure are counted as retrieval rejections (`records_without_structure`), never as compounds: a thin set is not a negative result.
