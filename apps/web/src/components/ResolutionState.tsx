import type { ResolutionCandidate, TargetResolution } from "../api/types";

interface ResolutionStateProps {
  status: TargetResolution["status"];
  query: string;
  notes: string[];
  candidates: ResolutionCandidate[];
  onPick: (identifier: string) => void;
}

/** What the user sees when a target query did not resolve to exactly one scope.
 *
 * An ambiguous query is never auto-resolved: the alternatives are shown with the
 * data needed to choose between them, and "no match" explicitly does not mean
 * "no inhibitors exist". */
export function ResolutionState({
  status,
  query,
  notes,
  candidates,
  onPick,
}: ResolutionStateProps) {
  if (status === "ambiguous") {
    return (
      <div className="state-banner" role="status">
        <div>
          <strong>{query}</strong> matches more than one protein. Pick the one you meant — the
          evidence scope is not chosen for you.
          <ul>
            {candidates.map((candidate) => (
              <li key={candidate.identifier}>
                <button className="evidence-link" onClick={() => onPick(candidate.identifier)}>
                  {candidate.identifier}
                </button>{" "}
                {candidate.name ?? "unnamed"}
                {candidate.organism ? ` · ${candidate.organism}` : ""}
                {candidate.target_type ? ` · ${candidate.target_type}` : ""}
              </li>
            ))}
          </ul>
        </div>
      </div>
    );
  }
  if (status === "not_found") {
    return (
      <div className="state-banner" role="status">
        <span>
          No protein record matched <strong>{query}</strong>. Check the gene symbol or use a
          UniProt accession (for example Q969D9). No record matched does not mean the target has
          no inhibitors — it means this deployment could not identify the target.
        </span>
      </div>
    );
  }
  if (status === "not_queried") {
    return (
      <div className="state-banner error" role="alert">
        <span>{notes.join(" ") || `The request for ${query} could not be issued.`}</span>
      </div>
    );
  }
  if (status === "failed") {
    return (
      <div className="state-banner error" role="alert">
        <span>
          The target source could not be reached, so <strong>{query}</strong> was not resolved.
          This is a source failure, not an empty result. {notes.join(" ")}
        </span>
      </div>
    );
  }
  return null;
}
