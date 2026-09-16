import { useQuery } from "@tanstack/react-query";
import { api } from "../api/client";

interface TopBarProps {
  onOpenProjects?: () => void;
  onOpenCorpus?: () => void;
  /** Stored analyses this owner can reopen (B-10). */
  onOpenAnalyses?: () => void;
}

/** The dataset badge shows the *actual* loaded sources (PROD-01): synthetic
 * demo data is labeled as demo; imported real sources show their real name,
 * and multiple datasets are counted rather than hidden behind one label. The
 * badge is also the button that opens the corpus inventory (B-01). */
export function TopBar({ onOpenProjects, onOpenCorpus, onOpenAnalyses }: TopBarProps) {
  const { data: health } = useQuery({
    queryKey: ["health"],
    queryFn: ({ signal }) => api.health(signal),
    staleTime: 60_000,
  });
  const { data: datasetInfo } = useQuery({
    queryKey: ["dataset"],
    queryFn: ({ signal }) => api.datasetInfo(signal),
    staleTime: 5 * 60_000,
  });

  const datasets = datasetInfo?.datasets ?? [];
  const latest = datasets[0];
  const others = datasets.length - 1;

  return (
    <header className="topbar">
      <div className="wordmark">
        SPA<span>go</span>
      </div>
      <div className="tagline">small molecule patent analysis</div>
      <div className="topbar-spacer" />
      {onOpenProjects && (
        <button className="btn btn-quiet" onClick={onOpenProjects}>
          Projects
        </button>
      )}
      {onOpenAnalyses && (
        <button className="btn btn-quiet" onClick={onOpenAnalyses}>
          Analyses
        </button>
      )}
      {latest && (
        <button
          type="button"
          className="dataset-badge"
          onClick={onOpenCorpus}
          disabled={!onOpenCorpus}
          aria-haspopup="dialog"
          title={
            (latest.synthetic
              ? "This deployment serves the synthetic demo fixture dataset. Identifiers and structures are illustrative, not scientific data."
              : `Source: ${latest.source_name} · ${latest.dataset_version}. Retrieved ${new Date(
                  latest.retrieved_at,
                ).toLocaleString()}.`) +
            (onOpenCorpus ? " Click for the loaded corpus inventory." : "")
          }
        >
          <span className="dot" aria-hidden="true" />
          {latest.synthetic ? "Demo dataset" : latest.source_name} · {latest.dataset_version}
          {others > 0 ? ` (+${others} more)` : ""}
        </button>
      )}
      {!latest && health?.dataset_version && (
        <button
          type="button"
          className="dataset-badge"
          onClick={onOpenCorpus}
          disabled={!onOpenCorpus}
          aria-haspopup="dialog"
          title={onOpenCorpus ? "Click for the loaded corpus inventory." : undefined}
        >
          <span className="dot" aria-hidden="true" />
          dataset · {health.dataset_version}
        </button>
      )}
    </header>
  );
}
