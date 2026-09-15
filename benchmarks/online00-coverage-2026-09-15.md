# ONLINE-00 coverage evidence — 2026-09-15

Live source coverage for the ONLINE-00 acceptance set. Raw records:
`online00-coverage-2026-09-15.json` (generated, not hand-written).

## How this was produced

```python
TargetResolutionService().resolve(query, "human", include_related=True)
TargetDiscoveryService().investigate(target, sources=("chembl", "bindingdb", "pubchem"))
```

Sources: UniProt REST (`rest.uniprot.org/uniprotkb/search`), ChEMBL web services
(`www.ebi.ac.uk/chembl/api/data`), BindingDB REST (`bindingdb.org/rest/getLigandsByUniprot`),
PubChem PUG REST (`pubchem.ncbi.nlm.nih.gov/rest/pug`). Query identifiers, per-source
counts, rejection reasons, versions and timings are in the JSON.

## Result

| Target | UniProt | Type | ChEMBL | BindingDB | PubChem | Small-molecule candidates | All candidates |
| --- | --- | --- | --- | --- | --- | --- | --- |
| TSLP (ligand) | Q969D9 | single protein | complete, 111 kept (3 no value) | complete, 3 kept | complete, 20 screening assays | **1** | 69 (68 peptide) |
| CD40LG (ligand) | P29965 | single protein | complete, 21 kept across 3 ChEMBL targets | **empty** (0 hits) | complete, 22 screening assays | **10** | 11 (1 peptide) |
| IL-6 (ligand) | P05231 | single protein | complete, 166 kept (246 kinetic records without a standard value) | complete, 9 kept | partial, 48 assays | **144** | 144 |
| IL-6R (receptor) | P08887 | single protein | complete, 1 kept | **failed** (HTTP 200, empty body) | complete, 17 screening assays | **1** | 1 |
| **EGFR (positive control)** | P00533 | single protein | partial, 2000 kept (bound reached) | complete, 974 kept | partial, 4609 assays | **2531** | 2549 (18 peptide) |

## What this evidence supports, and what it does not

- **The adapters work.** The EGFR positive control returns 2531 qualifying
  small-molecule candidates, so an empty or thin result for an acceptance target
  is a coverage fact about that target, not a broken pipeline. This control is
  required by the plan precisely so that empty responses cannot masquerade as a
  working adapter.
- **TSLP has almost no small-molecule coverage in these sources.** 110 of 111
  qualifying ChEMBL activities are peptides (9–14 residue), and ChEMBL's
  `molecule_type` reports them as `"Small molecule"`. Only classification by
  deterministic structure rules separates them; 1 genuine small molecule
  remains. BindingDB contributes 3 Kd values, all peptides.
- **CD40LG needs the interaction target.** ChEMBL records the ligand
  (CHEMBL3580491), the CD40L–CD40 interaction (CHEMBL4106122) and MAC1–CD40L
  (CHEMBL4106121). Retrieving only the single-protein record yields 1 candidate;
  including the interaction target yields 10 small molecules measured against
  the complex, all labelled `interaction_disruption` rather than direct binding.
- **IL-6R and CD40LG are thin.** 1 and 10 small-molecule candidates. BindingDB
  did not answer for IL-6R at all (recorded as `failed`, not as empty). No claim
  of inhibitor coverage for these targets is supported by this data.
- **Not assessed here:** potency ranking across assays (deliberately absent),
  patent-claim coverage, Markush scope, and whether any candidate is
  therapeutically useful. Patent linkage is reported per candidate; every
  candidate above currently has zero patent occurrences in the loaded corpus.

## Known coverage limits of this run

- PubChem contributes screening-assay *context* only (bounded AID lists), never
  measurements; `screening_assay` is a separate evidence class from direct
  binding.
- BindingDB's REST path supplies no assay description, species or construct, so
  those context fields are empty for BindingDB records.
- ChEMBL retrieval is bounded (2000 activities per target by default); EGFR
  reached that bound and is reported as `partial`.
- CRLF2 (TSLPR) has no ChEMBL target record, so the TSLP receptor side cannot be
  queried for activity through this path; the reviewed scope catalog records it.
