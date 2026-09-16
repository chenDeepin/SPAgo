import { useEffect, useRef, useState } from "react";
import { api, ApiError } from "../api/client";

interface ExportMenuProps {
  /** Patent-family scope. Exactly one of familyId/targetId is set. */
  familyId?: string;
  /** Target-investigation scope (ONLINE-00): exports candidates, including
   * those with no patent mapping. */
  targetId?: string;
  /** The candidate table's labelled modality filter, passed through as-is. */
  includeAllModalities?: boolean;
  /** B-33: the potency policy the screen's classes were computed under (nM).
   * It governs the file's `activity_class`/`reference_*` columns for both
   * scopes — the selection exports under the same rule the user is looking
   * at, not the deployment default. */
  activityThresholdNanomolar?: number | null;
  /** B-33: the screen's evidence-class selection. Applied to the
   * current-results scope only; an explicit selection names its own rows and
   * is not re-filtered. */
  evidenceClass?: string | null;
  documentId?: string | null;
  selectedIds: string[];
  /** Total of the plain list in the current family/document/target scope. */
  resultsTotal: number;
  /** Active structure filter, if any: "current results" then means the
   * structure result set, re-executed server-side at export time. */
  structureFilter: {
    mode: string;
    /** Raw query SMILES as entered; the server re-canonicalizes it. */
    smiles: string;
    threshold: number | null;
    total: number;
  } | null;
}

type ExportFormat = "csv" | "sdf";
type ExportScope = "selection" | "results";

/** Single Export owner (design contract 7): choose format and scope explicitly.
 * "Current results" exports the server-side scope — family, document, or the
 * active structure query — never just the loaded page, and the label names the
 * exact scope (PROD-02). */
export function ExportMenu({
  familyId,
  targetId,
  includeAllModalities = false,
  activityThresholdNanomolar = null,
  evidenceClass = null,
  documentId = null,
  selectedIds,
  resultsTotal,
  structureFilter,
}: ExportMenuProps) {
  const [open, setOpen] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const rootRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const onDown = (e: MouseEvent) => {
      if (rootRef.current && !rootRef.current.contains(e.target as Node)) setOpen(false);
    };
    window.addEventListener("mousedown", onDown);
    return () => window.removeEventListener("mousedown", onDown);
  }, []);

  const run = async (format: ExportFormat, scope: ExportScope) => {
    setBusy(true);
    setError(null);
    try {
      await api.exportFile({
        family_id: familyId ?? null,
        target_id: targetId ?? null,
        include_all_modalities: targetId ? includeAllModalities : undefined,
        document_id: scope === "results" && !structureFilter ? documentId : null,
        compound_ids: scope === "selection" ? selectedIds : null,
        structure_query:
          scope === "results" && structureFilter
            ? {
                mode: structureFilter.mode,
                smiles: structureFilter.smiles,
                threshold: structureFilter.mode === "similarity" ? structureFilter.threshold : null,
              }
            : null,
        // B-33: both travel with the file — the threshold as the policy behind
        // its class columns (any scope), the evidence-class filter as the
        // definition of "current results" (results scope only).
        activity_threshold_nm: targetId ? activityThresholdNanomolar : null,
        evidence_class: targetId && scope === "results" ? evidenceClass : null,
        format,
      });
      setOpen(false);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Export failed.");
    } finally {
      setBusy(false);
    }
  };

  const selectionDisabled = selectedIds.length === 0;
  const resultsLabel = structureFilter
    ? `Structure results (${structureFilter.total})`
    : targetId
      ? `Current candidates (${resultsTotal})`
      : documentId
        ? `Current document (${resultsTotal})`
        : `Current family (${resultsTotal})`;

  return (
    <div className="export-root" ref={rootRef}>
      <button
        className="btn btn-quiet"
        aria-expanded={open}
        aria-haspopup="menu"
        onClick={() => setOpen((o) => !o)}
      >
        Export ▾
      </button>
      {open && (
        <div className="export-menu" role="menu" aria-label="Export options">
          {error && (
            <div className="state-banner error" role="alert">
              <span>{error}</span>
            </div>
          )}
          <button
            role="menuitem"
            className="menu-item"
            disabled={busy || selectionDisabled}
            onClick={() => run("csv", "selection")}
          >
            CSV · Selected ({selectedIds.length})
          </button>
          <button
            role="menuitem"
            className="menu-item"
            disabled={busy || selectionDisabled}
            onClick={() => run("sdf", "selection")}
          >
            SDF · Selected ({selectedIds.length})
          </button>
          <div className="menu-sep" />
          <button
            role="menuitem"
            className="menu-item"
            disabled={busy}
            onClick={() => run("csv", "results")}
          >
            CSV · {resultsLabel}
          </button>
          <button
            role="menuitem"
            className="menu-item"
            disabled={busy}
            onClick={() => run("sdf", "results")}
          >
            SDF · {resultsLabel}
          </button>
          <p className="hint-note">
            {structureFilter
              ? "The structure query is re-run on the server, so the export covers every match, not just the loaded rows."
              : targetId
                ? "Current candidates export under the active evidence-class filter and threshold, so the file and the table state one rule. A selection exports exactly the chosen compounds under the same threshold, even when a filter would exclude them; a candidate with no patent mapping exports with empty patent columns rather than being dropped."
                : "Exports keep patent numbers, labels, evidence references, and dataset version."}
          </p>
        </div>
      )}
    </div>
  );
}
