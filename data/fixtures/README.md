# Fixture datasets

Synthetic, deterministic fixtures for SPAgo tests, seeds, and benchmarks.
**These are not scientific data.** Patent identifiers (`DEMO-*`), assignees,
titles, and texts are invented; SMILES are common textbook structures chosen to
exercise normalization behavior. Never use this dataset as evidence of any real
patent or compound property.

| File | Content | Schema version |
| --- | --- | --- |
| `patents/patent_documents_demo_fixture.parquet` | 3 synthetic patent documents in one family (`DEMO-FAMILY-1`) | `demo-fixture-v1` |
| `surechembl/surechembl_demo_fixture.parquet` | 13 structure-occurrence records shaped like a simplified SureChEMBL extract | `demo-fixture-v1` |
| `bioactivity/bioactivity_demo_fixture.parquet` | 6 synthetic IC50 measurements across two assays (same compound measured in both: kept separate by design) | `demo-fixture-v1` |
| `manifest.json` | source name, dataset version, row counts, sha256 checksums | — |

Regenerate with:

```bash
python data/fixtures/scripts/build_fixtures.py data/fixtures
```

## What the chemistry rows deliberately cover

- two records for the same molecule with different SMILES (must dedupe to one compound, two mentions);
- a racemic/stereo-specified pair (must remain distinct compounds);
- a salt and its parent acid (distinct identities at M0);
- a claim-only mention without section or page (evidence locator "not provided");
- an abstract mention with no section/page;
- one malformed SMILES (must surface as a validation warning, never a compound);
- per-document patent-local labels (`Example 07`, `Compound 12`, ...) that must
  never merge identities by label.

## Schema notes

The `surechembl` table is a *simplified* stand-in shaped for the adapter contract
(`document_id`, `compound_id`, `patent_label`, `smiles`, `source_field`,
`section`, `page`). Real SureChEMBL bulk releases have a different, richer schema;
the adapter is the only component allowed to know either schema.
