# Open-source adapter fixtures (ONLINE-00)

Purpose: let the UniProt / ChEMBL / BindingDB / PubChem adapter and discovery
tests run **without network access**, while still exercising the response shapes
the live services actually return.

## Provenance

Every file here was derived from a live response observed on **2026-09-15**
against the endpoints named below, then reduced to the fields the adapters read
and to a handful of records. Nothing here is invented: identifiers, gene names
and assay descriptions are the ones the services returned.

| File | Live source | Reduction |
| --- | --- | --- |
| `uniprot_TSLP_human.json` | `https://rest.uniprot.org/uniprotkb/search?query=(gene_exact:TSLP) AND (organism_id:9606)&format=json` | First 2 of 2 entries; protein-description prose trimmed. |
| `uniprot_ambiguous.json` | Synthetic arrangement of two real reviewed entries (TSLP and IL6) sharing no gene symbol; used only to exercise the ambiguity branch. | Marker `"fixture_derived": true`. |
| `chembl_targets_Q969D9.json` | `https://www.ebi.ac.uk/chembl/api/data/target.json?target_components__accession=Q969D9` | Full 1-record response with component text trimmed. |
| `chembl_targets_P29965.json` | `...?target_components__accession=P29965` | 3 records (single protein + 2 interactions). |
| `chembl_activities_TSLP.json` | `https://www.ebi.ac.uk/chembl/api/data/activity.json?target_chembl_id=CHEMBL3712931` | 4 of 114 records: a peptide percent-inhibition readout, a peptide Kd, a record without `standard_value`, and a genuine small molecule. |
| `chembl_documents_TSLP.json` | `https://www.ebi.ac.uk/chembl/api/data/document.json?document_chembl_id__in=…&only=document_chembl_id,patent_id,doi,pubmed_id,year,doc_type` | 2 document records in the reduced field set the adapter requests: one real patent document (`patent_id: US-20130089624-A1`) and the publication behind the TSLP activity (`CHEMBL4043230`). |
| `bindingdb_P05231.json` | `https://bindingdb.org/rest/getLigandsByUniprot?uniprot=P05231&response=application/json` | 2 of 9 affinities, including the `\|r\|` CXSMILES marker. |
| `bindingdb_P29965_empty.json` | `...uniprot=P29965...` | Real zero-hit response. |
| `pubchem_identity.json` | `https://pubchem.ncbi.nlm.nih.gov/rest/pug/compound/smiles/.../property/.../JSON` | One property row. |
| `pubchem_assays_TSLP.json` | `https://pubchem.ncbi.nlm.nih.gov/rest/pug/assay/target/genesymbol/TSLP/aids/JSON` | First 5 of 20 AIDs. |

## Rules

- These fixtures are **transport fixtures**, not scientific evidence. No
  measurement here may be used to support a potency or coverage claim; the
  live coverage matrix in `benchmarks/` is the evidence artifact.
- Values are as-reported by the source, including unit conventions the services
  do not state in the payload (BindingDB REST affinity is nanomolar).
- A fixture that represents a source *failure* is named accordingly and is
  tested as a failure, never as an empty success.
