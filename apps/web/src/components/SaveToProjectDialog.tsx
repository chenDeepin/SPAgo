import { useEffect, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api } from "../api/client";
import type { ProjectSummary } from "../api/types";
import { Modal } from "./Modal";

interface SaveToProjectDialogProps {
  familyId: string;
  familyKey: string;
  datasetVersion: string;
  sourceIsSynthetic: boolean;
  selectedIds: string[];
  onClose: () => void;
}

type SaveOutcome = "saved" | "already" | null;

/** Save dialog per design contract 6: scope is explicit (selection vs whole
 * family), the target project is confirmed, failures keep the dialog with a
 * retry, and re-saving never duplicates rows. Source versions are recorded
 * server-side from the saved rows (PROD-03). */
export function SaveToProjectDialog({
  familyId,
  familyKey,
  datasetVersion,
  sourceIsSynthetic,
  selectedIds,
  onClose,
}: SaveToProjectDialogProps) {
  const queryClient = useQueryClient();
  const [projectId, setProjectId] = useState<string>("");
  const [newName, setNewName] = useState("");
  const [mode, setMode] = useState<"selection" | "family">(
    selectedIds.length > 0 ? "selection" : "family",
  );
  const [outcome, setOutcome] = useState<SaveOutcome>(null);
  const [error, setError] = useState<string | null>(null);

  const projectsQuery = useQuery({
    queryKey: ["projects"],
    queryFn: ({ signal }) => api.projects(signal),
  });

  useEffect(() => {
    if (!projectId && projectsQuery.data && projectsQuery.data.length > 0) {
      setProjectId(projectsQuery.data[0].id);
    }
  }, [projectsQuery.data, projectId]);

  const saveMutation = useMutation({
    mutationFn: async () => {
      let targetId = projectId;
      if (newName.trim()) {
        const created = await api.createProject(newName.trim());
        targetId = created.id;
      }
      if (!targetId) throw new Error("Choose a project or enter a new project name.");
      return api.saveScope(targetId, {
        family_id: familyId,
        compound_ids: mode === "selection" ? selectedIds : null,
        dataset_version: datasetVersion,
      });
    },
    onSuccess: (result) => {
      setOutcome(result.created_rows > 0 ? "saved" : "already");
      setNewName("");
      queryClient.invalidateQueries({ queryKey: ["projects"] });
    },
    onError: (err) => {
      setError((err as Error).message);
    },
  });

  const projects: ProjectSummary[] = projectsQuery.data ?? [];
  const canSubmit = (projectId !== "" || newName.trim() !== "") && !saveMutation.isPending;

  return (
    <Modal title="Save to project" onClose={onClose}>
      {outcome === "saved" && (
        <div className="state-banner" role="status">
          <span>Saved to project.</span>
        </div>
      )}
      {outcome === "already" && (
        <div className="state-banner" role="status">
          <span>Already saved — nothing was duplicated.</span>
        </div>
      )}
      {error && (
        <div className="state-banner error" role="alert">
          <span>{error}</span>
          <span className="spacer" />
          <button
            className="btn btn-quiet"
            onClick={() => {
              setError(null);
              saveMutation.mutate();
            }}
          >
            Retry
          </button>
        </div>
      )}

      <div className="field-col">
        <label className="input-label">What to save</label>
        <div role="radiogroup" aria-label="Save scope" className="radio-col">
          <label className="radio-row">
            <input
              type="radio"
              name="scope"
              checked={mode === "selection"}
              disabled={selectedIds.length === 0}
              onChange={() => setMode("selection")}
            />
            <span>
              Selected compounds{" "}
              <span className="not-provided">
                {selectedIds.length === 0 ? "(nothing selected)" : `(${selectedIds.length})`}
              </span>
            </span>
          </label>
          <label className="radio-row">
            <input
              type="radio"
              name="scope"
              checked={mode === "family"}
              onChange={() => setMode("family")}
            />
            <span>
              Whole family <span className="mono">{familyKey}</span> (deduped compounds)
            </span>
          </label>
        </div>

        <label className="input-label" htmlFor="save-project">
          Target project
        </label>
        <select
          id="save-project"
          className="select-input"
          value={projectId}
          onChange={(e) => setProjectId(e.target.value)}
          disabled={newName.trim() !== ""}
        >
          {projects.length === 0 && <option value="">No projects yet</option>}
          {projects.map((p) => (
            <option key={p.id} value={p.id}>
              {p.name} ({p.item_count})
            </option>
          ))}
        </select>

        <label className="input-label" htmlFor="save-new-project">
          …or create a new project
        </label>
        <input
          id="save-new-project"
          className="text-input"
          type="text"
          placeholder="New project name"
          value={newName}
          onChange={(e) => setNewName(e.target.value)}
          maxLength={120}
        />

        <p className="hint-note">
          Source dataset <span className="mono">{datasetVersion}</span>
          {sourceIsSynthetic ? " (demo fixture)" : ""} is recorded with the saved
          items by the server at save time. Re-saving the same scope never duplicates entries.
        </p>
      </div>

      <div className="modal-actions">
        <button className="btn btn-quiet" onClick={onClose}>
          {outcome ? "Close" : "Cancel"}
        </button>
        <button
          className="btn btn-primary"
          disabled={!canSubmit}
          onClick={() => {
            setError(null);
            setOutcome(null);
            saveMutation.mutate();
          }}
        >
          {saveMutation.isPending ? "Saving…" : "Save"}
        </button>
      </div>
    </Modal>
  );
}
