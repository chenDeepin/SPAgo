import { useEffect, useRef, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { api } from "../api/client";
import type { ProjectDetail } from "../api/types";
import { Modal } from "./Modal";

interface ProjectsDialogProps {
  onClose: () => void;
  onOpen: (project: ProjectDetail) => void;
}

/** On-demand project selection (PROD-03): list saved projects and reopen one
 * in the workspace. No permanent dashboard — this is the same Modal surface
 * the save dialog uses. */
export function ProjectsDialog({ onClose, onOpen }: ProjectsDialogProps) {
  const [openingId, setOpeningId] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  const openingRequest = useRef<AbortController | null>(null);
  useEffect(() => () => openingRequest.current?.abort(), []);

  const projectsQuery = useQuery({
    queryKey: ["projects"],
    queryFn: ({ signal }) => api.projects(signal),
  });

  const open = async (id: string) => {
    openingRequest.current?.abort();
    const controller = new AbortController();
    openingRequest.current = controller;
    setOpeningId(id);
    setError(null);
    try {
      const detail = await api.project(id, controller.signal);
      if (!controller.signal.aborted) onOpen(detail);
    } catch (err) {
      if (!controller.signal.aborted) setError((err as Error).message || "The project could not be loaded.");
    } finally {
      if (!controller.signal.aborted) setOpeningId(null);
    }
  };

  const projects = projectsQuery.data ?? [];

  return (
    <Modal title="Open project" onClose={onClose}>
      {error && (
        <div className="state-banner error" role="alert">
          <span>{error}</span>
        </div>
      )}
      {projectsQuery.isError ? (
        <div className="state-banner error" role="alert">
          <span>{(projectsQuery.error as Error).message || "Projects could not be loaded."}</span>
          <button className="btn btn-quiet" onClick={() => projectsQuery.refetch()}>Retry</button>
        </div>
      ) : projectsQuery.isLoading ? (
        <p className="hint-note">Loading projects…</p>
      ) : projects.length === 0 ? (
        <p className="hint-note">
          No saved projects yet. Save a family or a compound selection from the
          results view first.
        </p>
      ) : (
        <ul className="project-list">
          {projects.map((p) => (
            <li key={p.id} className="project-row">
              <div>
                <div className="project-name">{p.name}</div>
                <div className="hint-note">
                  {p.item_count} saved item{p.item_count === 1 ? "" : "s"} ·{" "}
                  {new Date(p.created_at).toLocaleString()}
                </div>
              </div>
              <button
                className="btn btn-quiet"
                disabled={openingId !== null}
                onClick={() => open(p.id)}
              >
                {openingId === p.id ? "Opening…" : "Open"}
              </button>
            </li>
          ))}
        </ul>
      )}
      <p className="hint-note">
        Opening a project restores its family view and re-selects the compounds
        that were saved. Source versions are read from the saved records, so a
        later data import never silently changes what was saved.
      </p>
    </Modal>
  );
}
