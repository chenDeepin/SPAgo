import { useEffect, useRef, useState } from "react";
import { api, ApiError } from "../api/client";

interface ExportMenuProps {
  familyId: string;
  documentId: string | null;
  selectedIds: string[];
}

type ExportFormat = "csv" | "sdf";
type ExportScope = "selection" | "results";

/** Single Export owner (design contract 7): choose format and scope explicitly.
 * "Current results" exports the server-side scope, never just the loaded page. */
export function ExportMenu({ familyId, documentId, selectedIds }: ExportMenuProps) {
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
        family_id: familyId,
        document_id: scope === "results" ? documentId : null,
        compound_ids: scope === "selection" ? selectedIds : null,
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
            CSV · Current results
          </button>
          <button
            role="menuitem"
            className="menu-item"
            disabled={busy}
            onClick={() => run("sdf", "results")}
          >
            SDF · Current results
          </button>
          <p className="hint-note">
            Exports keep patent numbers, labels, evidence references, and dataset version.
          </p>
        </div>
      )}
    </div>
  );
}
