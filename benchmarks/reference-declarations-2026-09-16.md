# Source-declared document references — live measurement

Measured 2026-09-16T06:57:11+00:00 from the running build (`api_version` 0.1.0) by
`scripts/cohort_coverage.py --declarations` through the shipped ChEMBL
adapter. Live upstream calls; nothing was written to the database.

Bounds in force: 2000 activities per ChEMBL
target id, 8 document-metadata request(s).

A record's document reference is what the source declared. It is **not**
evidence that the compound occurs in that document in SPAgo's corpus, and it
is not a statement about patent coverage either way.

## Totals

2696 kept record(s) measured.

| Outcome | Records | Meaning |
| --- | --- | --- |
| `patent_declared` | 135 | the source's document declares a patent publication number |
| `doi_only` | 1351 | the document declares a DOI but no patent number |
| `document_unknown_to_source` | 1210 | the source does not know the cited document id |

## TSLP

TSLP — Thymic stromal lymphopoietin · UniProt Q969D9

ChEMBL target ids: CHEMBL3712931 · status complete · 1 page(s)

114 record(s) returned, 3 excluded (no structure or no numeric value), **111 kept**; 111 of them linked to a document.

| Outcome | Records |
| --- | --- |
| `doi_only` | 111 |

## CD40LG

CD40LG — CD40 ligand · UniProt P29965

ChEMBL target ids: CHEMBL3580491, CHEMBL4106121, CHEMBL4106122 · status complete, empty, complete · 3 page(s)

46 record(s) returned, 25 excluded (no structure or no numeric value), **21 kept**; 21 of them linked to a document.

| Outcome | Records |
| --- | --- |
| `doi_only` | 21 |

## IL6

IL6 — Interleukin-6 · UniProt P05231

ChEMBL target ids: CHEMBL1795129 · status complete · 3 page(s)

412 record(s) returned, 246 excluded (no structure or no numeric value), **166 kept**; 166 of them linked to a document.

| Outcome | Records |
| --- | --- |
| `patent_declared` | 135 |
| `doi_only` | 31 |

## IL6R

IL6R — Interleukin-6 receptor subunit alpha · UniProt P08887

ChEMBL target ids: CHEMBL2364155, CHEMBL3137266 · status complete, empty · 2 page(s)

5 record(s) returned, 4 excluded (no structure or no numeric value), **1 kept**; 1 of them linked to a document.

| Outcome | Records |
| --- | --- |
| `doi_only` | 1 |

## EGFR

EGFR — Epidermal growth factor receptor · UniProt P00533

ChEMBL target ids: CHEMBL203, CHEMBL2111431, CHEMBL2363049 · status partial, complete, complete · 15 page(s)

2598 record(s) returned, 200 excluded (no structure or no numeric value), **2397 kept**; 1187 of them linked to a document.

| Outcome | Records |
| --- | --- |
| `doi_only` | 1187 |
| `document_unknown_to_source` | 1210 |

> Activity retrieval stopped at the configured bound of 2000 records for CHEMBL203; the target has more.

---

`document_not_retrieved_bound` and `document_not_retrieved_failure` are facts about
this retrieval, not about the compounds: the lookup stopped before those documents
were resolved. They must never be rendered as "no patent".
