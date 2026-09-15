-- Preserve saved scientific identity when upstream records disappear.
-- UUID references deliberately survive source deletion; project ownership still
-- cascades. Existing identity snapshots must not be overwritten during upgrade.
ALTER TABLE project_items ADD COLUMN family_key text;
ALTER TABLE project_items ADD COLUMN compound_dataset_version text;
UPDATE project_items pi SET family_key = f.family_key
FROM patent_families f WHERE f.id = pi.family_id;
UPDATE project_items pi SET
    inchikey = COALESCE(pi.inchikey, c.inchikey),
    canonical_smiles = COALESCE(pi.canonical_smiles, c.canonical_smiles),
    compound_dataset_version = c.dataset_version
FROM compounds c WHERE c.id = pi.compound_id;
-- Legacy version labels cannot reconstruct historical source/version pairs.
-- Keep dataset_versions NULL to preserve that uncertainty.
ALTER TABLE project_items DROP CONSTRAINT project_items_family_id_fkey;
ALTER TABLE project_items DROP CONSTRAINT project_items_compound_id_fkey;

-- Source occurrence identity is the stable adapter UUID. A corrected structure
-- may change compound_id, and distinct source records can share a local label.
ALTER TABLE compound_mentions
    DROP CONSTRAINT compound_mentions_compound_id_document_id_patent_label_key;
