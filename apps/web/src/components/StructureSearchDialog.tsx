import { useEffect, useRef, useState } from "react";
import { api, ApiError } from "../api/client";
import type { CompoundRow } from "../api/types";
import { Modal } from "./Modal";
// Import order matters: this installs the `require` that ketcher-core's Raphael
// access needs, and ESM evaluates dependencies before this module's body.
import "./ketcher-require-shim";
import { StructureEditor } from "./StructureEditor";

interface StructureSearchDialogProps {
  familyId: string;
  scopeLabel: string;
  onClose: () => void;
  onResults: (results: StructureSearchSummary) => void;
}

/** Search results carry the full server paging contract plus the context they
 * were produced in, so stale responses can never be applied to a newer view. */
export interface StructureSearchSummary {
  familyId: string;
  requestKey: string;
  mode: string;
  query_canonical_smiles: string;
  threshold: number | null;
  total: number;
  offset: number;
  limit: number;
  rows: CompoundRow[];
  scores: Record<string, number>;
  requestParams: Record<string, unknown>;
}

const DEFAULT_THRESHOLD = 0.6;
const PAGE_SIZE = 100;

/** Basic format boundary only: a SMILES draft is a single token with no
 * whitespace. Chemical validity is decided server-side by RDKit (a 422 there
 * surfaces its reason) — [Na+], S, or any other legal but unusual input must
 * reach the server instead of being guessed away here. */
function formatBoundaryOk(value: string): boolean {
  const v = value.trim();
  return v.length > 0 && !/\s/.test(v);
}

/** Structure search dialog (design contract 8).
 *
 * Query input is a SMILES draft: the embedded editor writes into it when the
 * drawing changes, and the box can be typed or pasted into directly. The box is
 * what the search reads, so the two never disagree about what will be sent.
 * Nothing executes until "Run search" (explicit user action). Scope is fixed to
 * the current family. Closing the dialog aborts a running request; a late
 * response is discarded and never reaches the results view.
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
  const abortRef = useRef<AbortController | null>(null);
  const closedRef = useRef(false);

  // Closing cancels the in-flight request: no state updates, no onResults.
  useEffect(
    () => () => {
      closedRef.current = true;
      abortRef.current?.abort();
    },
    [],
  );

  const draftValid = formatBoundaryOk(smiles);

  const runSearch = async () => {
    setError(null);
    if (!draftValid) {
      setError(
        smiles.trim()
          ? "A SMILES string must be a single token without spaces."
          : "Draw or paste a structure first — the query is empty.",
      );
      return;
    }
    abortRef.current?.abort();
    const controller = new AbortController();
    abortRef.current = controller;
    setRunning(true);
    try {
      const params: Record<string, unknown> = {
        mode,
        smiles: smiles.trim(),
        limit: PAGE_SIZE,
      };
      if (mode === "similarity") params.threshold = threshold;
      const body = await api.structureSearch(familyId, params, controller.signal);
      if (controller.signal.aborted) return;
      const scores: Record<string, number> = {};
      const rows: CompoundRow[] = body.items.map((it) => {
        if (it.score != null) scores[it.compound.inchikey] = it.score;
        return { compound: it.compound, mentions: it.mentions, activity: [] };
      });
      onResults({
        familyId,
        requestKey: `${mode}|${body.query_inchikey}|${body.threshold ?? ""}|${Date.now()}`,
        mode,
        query_canonical_smiles: body.query_canonical_smiles,
        threshold: body.threshold,
        total: body.total,
        offset: body.offset,
        limit: body.limit,
        rows,
        scores,
        requestParams: params,
      });
    } catch (err) {
      if (controller.signal.aborted) return; // dialog closed or superseded
      setError(err instanceof ApiError ? err.message : "Search failed.");
    } finally {
      if (!controller.signal.aborted) setRunning(false);
    }
  };

  const stereoNote =
    mode === "similarity"
      ? "Fingerprint-based (Morgan radius 2): stereoisomers are not distinguished by similarity."
      : "Stereochemistry preserved where the query specifies it.";

  return (
    <Modal title="Structure search" onClose={onClose}>
      <div className="structsearch-body">
        <div className="structsearch-side" style={{ flex: "1 1 100%" }}>
          {/* The editor is the drawing input and writes its SMILES into the box
              below; neither action executes anything — a search still requires the
              explicit action at the bottom (AGENTS.md §14/§15). */}
          <StructureEditor
            initialSmiles={smiles}
            onChange={(next) => {
              setSmiles(next);
              setError(null);
            }}
          />
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
            Draw in the editor — each change writes its SMILES into the box above — or type/paste a
            SMILES string directly. The box is the query that runs; editing it does not start a
            search, and chemical validity is checked when the search runs.
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
            </div>
          )}

          <div className="input-label">Search scope</div>
          <div className="scope-static">Current family — {scopeLabel}</div>

          <div className="input-label">Stereochemistry</div>
          <div className="scope-static">{stereoNote}</div>

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
