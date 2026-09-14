-- M2: indexed chemistry storage for exact/substructure/similarity search.
-- Requires the rdkit extension (created at db init). Compounds whose SMILES
-- cannot be parsed keep m = NULL and are never returned by structure search.
-- NOTE: the Debian cartridge (2022.09 / extversion 4.2.0) names the base type
-- `mol`; newer cartridge releases renamed it to `molecule`.

ALTER TABLE compounds ADD COLUMN IF NOT EXISTS m mol;

UPDATE compounds SET m = mol_from_smiles(canonical_smiles) WHERE m IS NULL;

-- Substructure prefilter index.
CREATE INDEX IF NOT EXISTS idx_compounds_m_gist ON compounds USING GIST (m gist_mol_ops);

-- Morgan fingerprint similarity index (tanimoto threshold handled per query
-- via rdkit.gin_threshold + explicit score filter in services).
SET rdkit.gin_threshold = 0.5;
CREATE INDEX IF NOT EXISTS idx_compounds_mfp2_gin
    ON compounds USING GIN (morganbv_fp(m) gin_bfp_ops);
