interface EmptyStateProps {
  demoHint?: string | null;
}

export function EmptyState({ demoHint }: EmptyStateProps) {
  return (
    <div className="empty-state">
      <h1>Inspect patent chemistry</h1>
      <p>Enter a patent publication number to view its family, extracted compounds, and source evidence.</p>
      {demoHint && (
        <p className="hint">
          This deployment serves a synthetic demo dataset — try <code>{demoHint}</code>.
        </p>
      )}
    </div>
  );
}

export function SkeletonRows({ rows = 5 }: { rows?: number }) {
  return (
    <div role="status" aria-label="Loading compounds">
      {Array.from({ length: rows }, (_, i) => (
        <div className="skeleton-row" key={i}>
          <div className="skeleton" style={{ width: 144, height: 80 }} />
          <div style={{ flex: 1, display: "grid", gap: 8 }}>
            <div className="skeleton" style={{ width: "55%", height: 14 }} />
            <div className="skeleton" style={{ width: "35%", height: 12 }} />
          </div>
          <div className="skeleton" style={{ width: 110, height: 14 }} />
        </div>
      ))}
    </div>
  );
}

interface StateBannerProps {
  kind: "error";
  message: string;
  onRetry?: () => void;
}

export function StateBanner({ kind, message, onRetry }: StateBannerProps) {
  return (
    <div className={`state-banner ${kind}`} role="alert">
      <span>{message}</span>
      <span className="spacer" />
      {onRetry && (
        <button className="btn btn-quiet" onClick={onRetry}>
          Retry
        </button>
      )}
    </div>
  );
}

export function NoStructuresNote({ scopeLabel }: { scopeLabel: string }) {
  return (
    <div className="state-banner">
      <span>
        The current source provides no structures for {scopeLabel}. Metadata is shown; no structure
        extraction is attempted automatically.
      </span>
    </div>
  );
}
