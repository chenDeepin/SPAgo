import { useEffect, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api } from "../api/client";
import type { ProjectSummary } from "../api/types";
import { Modal } from "./Modal";

interface SaveCandidatesDialogProps {
  targetId: string;
  targetKey: string;
  selectedIds: string[];
  onClose: () => void;
}

type SaveOutcome = "saved" | "already" | null;

/** Save target candidates to a project (ONLINE-00 C).
 *
 * Candidates that have no patent mapping are saved through the same flow as
 * patent-linked compounds: the item records its target scope and an identity
 * snapshot, so reopening the project still shows what was saved. */
export function SaveCandidatesDialog({
  targetId,
  targetKey,
  selectedIds,
  onClose,
}: SaveCandidatesDialogProps) {
  const queryClient = useQueryClient();
  const [projectId, setProjectId] = useState<string>("");
  const [newName, setNewName] = useState("");
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
      let targetProjectId = projectId;
      if (newName.trim()) {
        const created = await api.createProject(newName.trim());
        targetProjectId = created.id;
      }
      if (!targetProjectId) throw new Error("Choose a project or enter a new project name.");
      return api.saveCandidates(targetProjectId, {
        target_id: targetId,
        compound_ids: selectedIds,
      });
    },
    onSuccess: (result) => {
      setOutcome(result.created_rows > 0 ? "saved" : "already");
      setNewName("");
      queryClient.invalidateQueries({ queryKey: ["projects"] });
    },
    onError: (err) => setError((err as Error).message),
  });

  const projects: ProjectSummary[] = projectsQuery.data ?? [];
  const canSubmit = (projectId !== "" || newName.trim() !== "") && selectedIds.length > 0;

  return (
    <Modal title={`Save ${selectedIds.length} candidate(s)`} onClose={onClose}>
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

      {selectedIds.length === 0 && (
        <div className="state-banner" role="status">
          <span>Select at least one candidate first.</span>
        </div>
      )}

      <div className="field-col">
        <label className="input-label" htmlFor="candidate-save-project">
          Target project
        </label>
        <select
          id="candidate-save-project"
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

        <label className="input-label" htmlFor="candidate-save-new">
          …or create a new project
        </label>
        <input
          id="candidate-save-new"
          className="text-input"
          type="text"
          placeholder="New project name"
          value={newName}
          onChange={(e) => setNewName(e.target.value)}
          maxLength={120}
        />

        <p className="hint-note">
          Saved under target scope <span className="mono">{targetKey}</span>. Candidates{" "}
          <strong>without a patent mapping</strong> are saved the same way: the item keeps its
          target, its source versions and an identity snapshot rather than being discarded.
        </p>
      </div>

      <div className="modal-actions">
        <button className="btn btn-quiet" onClick={onClose}>
          {outcome ? "Close" : "Cancel"}
        </button>
        <button
          className="btn btn-primary"
          disabled={!canSubmit || saveMutation.isPending}
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
