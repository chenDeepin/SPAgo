import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { api } from "../api/client";
import type { ProjectAnalysisRef } from "../api/types";
import { Modal } from "./Modal";

interface ProjectAnalysesDialogProps {
  projectName: string;
  analyses: ProjectAnalysisRef[];
  onClose: () => void;
}

const SCOPE_LABELS: Record<string, string> = {
  family: "patent family",
  document: "document",
  target: "target",
};

/** The stored analyses a project references (B-29).
 *
 * Reading one is a pure read of the stored artifact — no provider call — and
 * its own staleness statement renders with it, so a reopened project shows the
 * analysis that explained the selection together with whether the data behind
 * it has moved since. A reference whose analysis row is gone stays readable
 * from its snapshot and is marked, exactly like a vanished compound item. */
export function ProjectAnalysesDialog({ projectName, analyses, onClose }: ProjectAnalysesDialogProps) {
  const [openId, setOpenId] = useState<string | null>(null);

  const detailQuery = useQuery({
    queryKey: ["analysis", openId],
    queryFn: ({ signal }) => api.analysis(openId as string, signal),
    enabled: openId !== null,
    staleTime: 60_000,
  });
  const detail = detailQuery.data;

  return (
    <Modal title={`Analyses in ${projectName}`} onClose={onClose} wide>
      {analyses.length === 0 ? (
        <p className="hint-note">
          No analysis is attached to this project. Attach one from the Analyses dialog: open the
          stored analysis and use “Add to project”.
        </p>
      ) : (
        <ul className="analyses-list">
          {analyses.map((ref) => (
            <li className="analyses-item" key={ref.id}>
              <div className="analyses-head">
                <button
                  className="analyses-open"
                  aria-expanded={openId === ref.analysis_id}
                  disabled={ref.analysis_missing}
                  onClick={() =>
                    setOpenId(openId === ref.analysis_id ? null : ref.analysis_id)
                  }
                >
                  <span className="analyses-scope">{SCOPE_LABELS[ref.scope] ?? ref.scope}</span>{" "}
                  <span className="mono">{ref.scope_label}</span>
                </button>
                <span className="analyses-meta">
                  {ref.provider}
                  {ref.model ? ` · ${ref.model}` : ""} · data {ref.dataset_version ?? "not recorded"}
                  {ref.prompt_version ? ` · prompt ${ref.prompt_version}` : ""}
                </span>
              </div>
              {ref.analysis_missing && (
                <div className="analyses-stale" role="status">
                  <strong>The stored analysis is gone.</strong> The snapshot above is what was
                  attached on {new Date(ref.added_at).toLocaleString()}; the reference stays
                  readable and marked rather than silently disappearing.
                </div>
              )}
              {openId === ref.analysis_id && (
                <div className="analyses-detail">
                  {detailQuery.isLoading ? (
                    <p className="hint-note">Reading the stored analysis…</p>
                  ) : detailQuery.isError ? (
                    <div className="state-banner error" role="alert">
                      <span>{(detailQuery.error as Error).message}</span>
                    </div>
                  ) : detail ? (
                    <>
                      <p className="hint-note">
                        {detail.exact_check?.same_inputs === true
                          ? "The inputs are unchanged, so this is what the same request returns now."
                          : detail.exact_check?.same_inputs === false
                            ? "The inputs have changed since; this text is the stored one, not a fresh answer."
                            : ""}
                        {detail.stale ? ` May be out of date: ${detail.stale_reasons.join(" ")}` : ""}
                      </p>
                      <pre className="ai-summary-text">{detail.text}</pre>
                      <div className="analyses-actions">
                        <button
                          className="btn btn-quiet"
                          onClick={() =>
                            void api
                              .exportAnalysis({ analysis_id: detail.analysis_id, scope: detail.scope })
                              .catch(() => undefined)
                          }
                        >
                          Export .md
                        </button>
                      </div>
                    </>
                  ) : null}
                </div>
              )}
            </li>
          ))}
        </ul>
      )}
      <p className="hint-note">
        Opening an attached analysis is a read of the stored artifact — no model call, no new cost.
        The export carries the scope, model, prompt and policy header with the text.
      </p>
    </Modal>
  );
}
