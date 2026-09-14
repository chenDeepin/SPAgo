import { useState } from "react";
import { api, ApiError } from "../api/client";
import type { CompoundRow } from "../api/types";
import { Modal } from "./Modal";

interface StructureSearchDialogProps {
  familyId: string;
  scopeLabel: string;
  onClose: () => void;
  onResults: (results: StructureSearchSummary | null) => void;
}

export interface StructureSearchSummary {
  mode: string;
  total: number;
  query_canonical_smiles: string;
  threshold: number | null;
  rows: CompoundRow[];
  scores: Record<string, number>;
}

const DEFAULT_THRESHOLD = 0.6;

function looksLikeSmiles(value: string): boolean {
  // Cheap client-side guard: non-empty, no whitespace blobs, contains at least
  // one atom token. Authoritative validation happens server-side via RDKit.
  const v = value.trim();
  if (!v || /\s/.test(v)) return false;
  return /[A-Za-z]/.test(v) && /[CNOc]/.test(v);
}

/** Structure search dialog (M2, design contract 8).
 *
 * Query input is a SMILES draft: editing/pasting only changes the draft —
 * nothing executes until "Run search" (explicit user action). Scope is fixed
 * to the current family; stereochemistry is preserved where specified.
 *
 * Note: the embedded Ketcher editor was planned here, but ketcher 2.28 and
 * 3.14 both crash at mount inside the Vite production build (packaging-level
 * incompatibility, recorded in docs/plans). SMILES paste is the M2 input;
 * Ketcher embedding returns once bundling is resolved.
 */
export function StructureSearchDialog({
  familyId,
  scopeLabel,
  onClose,
  onResults,
}: StructureSearchDialogProps) {
  const [smiles, setSmiles] = useState("");
  const [mode, setMode] = useState<"exact" | "substructure" | "similarity">("substructure");
  const [threshold, setThreshold] = useState(DEFAULT_THRESHOLD);
  const [running, setRunning] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const draftValid = looksLikeSmiles(smiles);

  const runSearch = async () => {
    setError(null);
    if (!draftValid) {
      setError(
        smiles.trim()
          ? "This does not look like a SMILES string — paste a structure such as CC(=O)Oc1ccccc1C(=O)O."
          : "Draw or paste a structure first — the query is empty.",
      );
      return;
    }
    setRunning(true);
    try {
      const params: Record<string, unknown> = { mode, smiles: smiles.trim(), limit: 100 };
      if (mode === "similarity") params.threshold = threshold;
      const body = await api.structureSearch(familyId, params);
      const scores: Record<string, number> = {};
      const rows: CompoundRow[] = body.items.map((it) => {
        if (it.score != null) scores[it.compound.inchikey] = it.score;
        return { compound: it.compound, mentions: it.mentions, activity: [] };
      });
      onResults({
        mode,
        total: body.total,
        query_canonical_smiles: body.query_canonical_smiles,
        threshold: body.threshold,
        rows,
        scores,
      });
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Search failed.");
    } finally {
      setRunning(false);
    }
  };

  return (
    <Modal title="Structure search" onClose={onClose}>
      <div className="structsearch-body">
        <div className="structsearch-side" style={{ flex: "1 1 100%" }}>
          <label className="input-label" htmlFor="struct-smiles">
            Structure (SMILES)
          </label>
          <textarea
            id="struct-smiles"
            className="text-input mono struct-smiles-input"
            placeholder="Paste a SMILES string, e.g. CC(=O)Oc1ccccc1C(=O)O"
            value={smiles}
            onChange={(e) => {
              setSmiles(e.target.value);
              setError(null);
            }}
            rows={3}
            spellCheck={false}
          />
          <p className="hint-note">
            The embedded structure editor (Ketcher) is deferred — paste a SMILES string for now.
            Editing does not start a search.
          </p>

          <div className="input-label">Search mode</div>
          <div role="radiogroup" aria-label="Search mode" className="radio-col">
            <label className="radio-row">
              <input type="radio" name="mode" checked={mode === "exact"} onChange={() => setMode("exact")} />
              <span>Exact</span>
            </label>
            <label className="radio-row">
              <input
                type="radio"
                name="mode"
                checked={mode === "substructure"}
                onChange={() => setMode("substructure")}
              />
              <span>Substructure</span>
            </label>
            <label className="radio-row">
              <input type="radio" name="mode" checked={mode === "similarity"} onChange={() => setMode("similarity")} />
              <span>Similarity</span>
            </label>
          </div>

          {mode === "similarity" && (
            <div className="sim-controls">
              <label className="input-label" htmlFor="sim-threshold">
                Tanimoto threshold
              </label>
              <input
                id="sim-threshold"
                type="range"
                min={0.3}
                max={1}
                step={0.05}
                value={threshold}
                onChange={(e) => setThreshold(Number(e.target.value))}
              />
              <span className="mono">{threshold.toFixed(2)}</span>
              <p className="hint-note">Morgan fingerprints (radius 2), Tanimoto similarity.</p>
            </div>
          )}

          <div className="input-label">Search scope</div>
          <div className="scope-static">Current family — {scopeLabel}</div>

          <div className="input-label">Stereochemistry</div>
          <div className="scope-static">Preserve where specified</div>

          {error && (
            <div className="state-banner error" role="alert">
              <span>{error}</span>
            </div>
          )}
        </div>
      </div>

      <div className="modal-actions">
        <button className="btn btn-quiet" onClick={onClose}>
          Cancel
        </button>
        <button
          className="btn btn-primary"
          disabled={running}
          onClick={runSearch}
          aria-disabled={!draftValid}
        >
          {running ? "Searching…" : "Run search"}
        </button>
      </div>
    </Modal>
  );
}
