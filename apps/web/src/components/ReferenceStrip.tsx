import { useEffect, useState } from "react";
import type { ReferenceVerdict } from "../api/types";

interface ReferenceStripProps {
  verdict: ReferenceVerdict | null;
  loading: boolean;
  error: string | null;
  /** Explicit user-stated threshold in µM, or null for the deployment policy. */
  thresholdOverrideMicromolar: number | null;
  onApplyThreshold: (micromolar: number | null) => void;
  /** Opens the compound's evidence in the existing inspector. */
  onSelectCompound: (compoundId: string) => void;
  /** Opens the add-rows dialog (ONLINE-07). */
  onAddRows: () => void;
}

const MICROMOLAR_TO_NANOMOLAR = 1000;

/** Shows the class of one measurement in the verdict's own vocabulary. */
export function activityClassLabel(value: string | null | undefined): string {
  switch (value) {
    case "active":
      return "active";
    case "weak":
      return "weak";
    case "unknown":
      return "undecided";
    case "not_applicable":
      return "not a potency";
    default:
      return value ?? "not classified";
  }
}

/** The potency-reference verdict for a target, under an explicit policy.
 *
 * This is the honest answer to "is this a usable starting set?" — a count with
 * its rule, not a conclusion. The threshold is editable because the threshold is
 * a *policy*, and a policy the reader cannot restate is a hidden assumption. The
 * verdict is recomputed server-side from the stored rows on every change, so no
 * stale class can survive a threshold change. */
export function ReferenceStrip({
  verdict,
  loading,
  error,
  thresholdOverrideMicromolar,
  onApplyThreshold,
  onSelectCompound,
  onAddRows,
}: ReferenceStripProps) {
  const [draft, setDraft] = useState<string>("");

  // The input follows the applied value, including a reset to the deployment
  // policy, without becoming a second source of truth.
  useEffect(() => {
    setDraft(
      thresholdOverrideMicromolar != null
        ? String(thresholdOverrideMicromolar)
        : verdict
          ? String(verdict.policy.threshold_nm / MICROMOLAR_TO_NANOMOLAR)
          : "",
    );
  }, [thresholdOverrideMicromolar, verdict?.policy.threshold_nm]);

  if (loading && !verdict) {
    return (
      <div className="reference-strip" role="status">
        <span className="skeleton-note">Computing the potency reference…</span>
      </div>
    );
  }

  if (error) {
    return (
      <div className="reference-strip reference-strip-error" role="alert">
        <span>
          The potency reference could not be computed: {error} This is a service failure, not a
          finding about the target.
        </span>
      </div>
    );
  }

  if (!verdict) {
    return (
      <div className="reference-strip" role="status">
        <span className="not-provided">
          No stored measurement for this target yet, so no reference can be stated.
        </span>
      </div>
    );
  }

  const parsed = Number(draft);
  const draftValid = Number.isFinite(parsed) && parsed > 0;
  const appliedMicromolar =
    thresholdOverrideMicromolar ?? verdict.policy.threshold_nm / MICROMOLAR_TO_NANOMOLAR;
  const changed = draftValid && parsed !== appliedMicromolar;

  return (
    <div className="reference-strip" aria-label="Potency reference verdict">
      <div className="reference-line">
        <span
          className={`reference-verdict ${verdict.qualifies ? "reference-yes" : "reference-no"}`}
        >
          {verdict.qualifies ? "Reference set" : "No reference set"}
        </span>
        <span className="reference-reason">{verdict.reason}</span>
      </div>

      <div className="reference-counts">
        <span>
          <strong>{verdict.compounds}</strong> in-scope compound
          {verdict.compounds === 1 ? "" : "s"}
        </span>
        <span>
          <strong>{verdict.compounds_active}</strong> at or below{" "}
          {verdict.policy.threshold_label}
        </span>
        <span>{verdict.compounds_weak} above it</span>
        <span>{verdict.compounds_unknown} undecided</span>
        {verdict.compounds_not_applicable > 0 && (
          <span>{verdict.compounds_not_applicable} not a potency</span>
        )}
               <span>
                 {verdict.measurements} in-scope record{verdict.measurements === 1 ? "" : "s"}
               </span>
        {verdict.active_compounds_outside_scope > 0 && (
          <span className="reference-warn">
            {verdict.active_compounds_outside_scope} active outside the modality scope
          </span>
        )}
        {verdict.records_without_structure > 0 && (
          <span title="A source reported a value without a structure SPAgo can draw. Counted as a rejection, not as a measurement.">
            {verdict.records_without_structure} source record
            {verdict.records_without_structure === 1 ? "" : "s"} without a public structure
          </span>
        )}
        {verdict.supplement_remarks > 0 && (
          <span title="Rows a person added by hand that carry a value but no public structure. Kept as remarks: never counted as compounds or measurements, never drawn.">
            {verdict.supplement_remarks} literature remark
            {verdict.supplement_remarks === 1 ? "" : "s"} added by hand
          </span>
        )}
        {verdict.potential_duplicates > 0 && (
          <span>{verdict.potential_duplicates} flagged as duplicate references</span>
        )}
        {verdict.truncated && (
          <span className="reference-warn">
            the measurement set is larger than the verdict reads, so these counts are not complete
          </span>
        )}
      </div>

      {verdict.actives.length > 0 && (
        <div className="reference-actives">
          <span className="fineprint">Strongest reports:</span>
          {verdict.actives.map((active) => (
            <button
              key={active.measurement_id ?? active.compound_id}
              className="evidence-link"
              title={`${active.evidence_class} · reported by ${active.source_name}`}
              onClick={() => onSelectCompound(active.compound_id)}
            >
              {active.potency_label}
              {active.potential_duplicate ? " (duplicate reference)" : ""}
            </button>
          ))}
        </div>
      )}

      <div className="reference-policy">
        <label className="reference-threshold">
          Threshold{" "}
          <input
            className="text-input reference-threshold-input"
            type="number"
            min="0"
            step="any"
            value={draft}
            onChange={(e) => setDraft(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter" && draftValid) onApplyThreshold(parsed);
            }}
            aria-label="Potency threshold in micromolar"
          />{" "}
          µM
        </label>
        <button
          className="btn btn-quiet"
          disabled={!draftValid || !changed}
          onClick={() => onApplyThreshold(parsed)}
        >
          Apply
        </button>
              {thresholdOverrideMicromolar != null && (
                <button className="btn btn-quiet" onClick={() => onApplyThreshold(null)}>
                  Use deployment policy
                </button>
              )}
              {/* ONLINE-07: the one place a person's own reading enters SPAgo, offered
                  where the thin set is visible rather than in a global menu. */}
              <button className="btn btn-quiet" onClick={onAddRows}>
                Add a row by hand
              </button>
        <span className="fineprint">
          Policy {verdict.policy.version}
          {thresholdOverrideMicromolar != null ? " · threshold set in this session" : ""} ·{" "}
          {verdict.policy.scope_note}
        </span>
      </div>

      <p className="fineprint reference-footnote">
        A deterministic count under the policy above, recomputed from the stored measurements — it
        is not a biological conclusion and not a claim about the literature. Different endpoint
        types are never compared or ranked.
      </p>
    </div>
  );
}
