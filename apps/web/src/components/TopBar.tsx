import { useQuery } from "@tanstack/react-query";
import { api } from "../api/client";

export function TopBar() {
  const { data: health } = useQuery({
    queryKey: ["health"],
    queryFn: ({ signal }) => api.health(signal),
    staleTime: 60_000,
  });

  return (
    <header className="topbar">
      <div className="wordmark">
        SPA<span>go</span>
      </div>
      <div className="tagline">small molecule patent analysis</div>
      <div className="topbar-spacer" />
      {health?.dataset_version && (
        <div
          className="dataset-badge"
          title="This deployment serves the synthetic demo fixture dataset. Identifiers and structures are illustrative, not scientific data."
        >
          <span className="dot" aria-hidden="true" />
          Demo dataset · {health.dataset_version}
        </div>
      )}
    </header>
  );
}
