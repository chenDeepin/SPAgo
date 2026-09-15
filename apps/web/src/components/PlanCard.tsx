import type { PlanStep, SearchPlanResponse } from "../api/types";

interface PlanCardProps {
  plan: SearchPlanResponse;
  working: boolean;
  error: string | null;
  onRun: () => void;
  onDiscard: () => void;
  /** Editable parameters, keyed by step index and parameter name. */
  edits: Record<string, string>;
  onEdit: (stepIndex: number, name: string, value: string) => void;
}

/** The compact interpretation of a request, shown before anything runs.
 *
 * Its job is to make the plan reviewable: which operations will run, with which
 * parameters, what could not be interpreted, and which steps are expensive. It
 * never hides an unresolved part of the request, and the Run action is explicit
 * because several steps trigger real work (structure search, open-database
 * retrieval). */
export function PlanCard({
  plan,
  working,
  error,
  onRun,
  onDiscard,
  edits,
  onEdit,
}: PlanCardProps) {
  const nothingToRun = plan.steps.length === 0;

  return (
    <div className="plan-card" role="group" aria-label="Interpreted request">
      <div className="plan-head">
        <strong>Interpretation</strong>
        <span className="fineprint">
          {plan.producer === "llm" ? "model-interpreted" : "deterministic identifiers only"}
          {plan.model ? ` · ${plan.model}` : ""} · plan {plan.plan_version}
        </span>
        <span className="spacer" />
        <button className="btn btn-quiet" onClick={onDiscard}>
          Discard
        </button>
        <button className="btn btn-primary" onClick={onRun} disabled={working || nothingToRun}>
          {working ? "Running…" : "Run"}
        </button>
      </div>

      {plan.steps.length > 0 && (
        <ol className="plan-steps">
          {plan.steps.map((step: PlanStep, index: number) => (
            <li key={`${step.op}-${index}`}>
              <span className="mono">{step.op}</span>
              {step.expensive && <span className="badge badge-peptide">expensive</span>}
              <div className="fineprint">{step.description}</div>
              <div className="plan-params">
                {Object.entries(step.parameters).map(([name, value]) => {
                  const key = `${index}:${name}`;
                  const editable =
                    name === "threshold" ||
                    name === "species" ||
                    name === "target_query" ||
                    name === "publication_number" ||
                    name === "limit";
                  return (
                    <label className="plan-param" key={key}>
                      <span className="mono">{name}</span>
                      {editable ? (
                        <input
                          className="text-input"
                          type="text"
                          value={edits[key] ?? String(value)}
                          onChange={(e) => onEdit(index, name, e.target.value)}
                          aria-label={`${name} for step ${index + 1}`}
                        />
                      ) : (
                        <span className="mono">{String(value)}</span>
                      )}
                    </label>
                  );
                })}
              </div>
            </li>
          ))}
        </ol>
      )}

      {plan.unresolved.length > 0 && (
        <div className="state-banner" role="status">
          <div>
            <strong>Not interpreted:</strong>{" "}
            {plan.unresolved.map((item, index) => (
              <span key={`${item}-${index}`}>
                {index > 0 && ", "}
                {item}
              </span>
            ))}
            <div className="fineprint">
              These parts were not turned into operations. SPAgo does not invent a target, a
              structure, a potency threshold or an assay condition to fill the gap — rephrase,
              narrow the request, or use manual search.
            </div>
          </div>
        </div>
      )}

      {plan.clarification_required && plan.steps.length > 0 && (
        <div className="state-banner" role="status">
          <span>
            Part of this request is outside the supported operations. Running executes only the
            steps listed above.
          </span>
        </div>
      )}

      {error && (
        <div className="state-banner error" role="alert">
          <span>{error}</span>
        </div>
      )}

      <p className="fineprint">{plan.note}</p>
    </div>
  );
}
