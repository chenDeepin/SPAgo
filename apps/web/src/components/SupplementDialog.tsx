import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api } from "../api/client";
import type { SupplementImport, SupplementRowInput } from "../api/types";
import { Modal } from "./Modal";
import { activityClassLabel } from "./ReferenceStrip";

interface SupplementDialogProps {
  targetId: string;
  targetKey: string;
  onClose: () => void;
  /** Opens a stored compound's evidence in the existing inspector. */
  onSelectCompound: (compoundId: string) => void;
}

/** One editable row, kept as strings so nothing is silently coerced. */
interface DraftRow {
  key: string;
  name: string;
  note: string;
  smiles: string;
  activityType: string;
  value: string;
  unit: string;
  relation: string;
  doi: string;
  pmid: string;
  patentNumber: string;
}

let draftCounter = 0;

function emptyRow(): DraftRow {
  draftCounter += 1;
  return {
    key: `draft-${draftCounter}`,
    name: "",
    note: "",
    smiles: "",
    activityType: "IC50",
    value: "",
    unit: "nM",
    relation: "=",
    doi: "",
    pmid: "",
    patentNumber: "",
  };
}

const EMPTY = "";

/** Turn a draft into the submitted shape, or state why it cannot be sent.
 *
 * The client refuses locally for the same reasons the server does (a missing
 * note, a value without an endpoint), so the user reads the reason next to the
 * field instead of after a round trip. The server still validates: this is a
 * convenience, not the contract.
 */
function toRow(draft: DraftRow): { row?: SupplementRowInput; problem?: string } {
  if (!draft.name.trim()) return { problem: "name is required" };
  if (!draft.note.trim()) {
    return { problem: "a note is required: it is this row's provenance" };
  }
  const value = draft.value.trim() === "" ? null : Number(draft.value);
  if (value != null && (!Number.isFinite(value) || value <= 0)) {
    return { problem: "value must be a positive number" };
  }
  if (value != null && (!draft.activityType.trim() || !draft.unit.trim())) {
    return { problem: "a value must state its endpoint and unit" };
  }
  if (value == null && (draft.activityType.trim() || draft.unit.trim())) {
    return { problem: "state a value, or clear the endpoint and unit" };
  }
  return {
    row: {
      name: draft.name.trim(),
      note: draft.note.trim(),
      smiles: draft.smiles.trim() || null,
      activity_type: draft.activityType.trim() || null,
      value,
      unit: draft.unit.trim() || null,
      relation: draft.relation || "=",
      doi: draft.doi.trim() || null,
      pmid: draft.pmid.trim() || null,
      patent_number: draft.patentNumber.trim() || null,
    },
  };
}

/** Add literature/patent rows to a target by hand (ONLINE-07).
 *
 * The dialog exists because a retrieved set can be thin or empty for a target
 * someone is actually working on, and the honest response is to record what the
 * reader knows — attributed to them — instead of leaving the target looking
 * unstudied. Everything here is labelled as user-curated: it is never mixed into
 * source data, never drawn as a structure that was not published, and it is
 * counted in the reference verdict as its own number. */
export function SupplementDialog({
  targetId,
  targetKey,
  onClose,
  onSelectCompound,
}: SupplementDialogProps) {
  const queryClient = useQueryClient();
  const [rows, setRows] = useState<DraftRow[]>(() => [emptyRow()]);
  const [result, setResult] = useState<SupplementImport | null>(null);
  const [error, setError] = useState<string | null>(null);

  const remarksQuery = useQuery({
    queryKey: ["target-supplement-remarks", targetId],
    queryFn: ({ signal }) => api.targetSupplementRemarks(targetId, signal),
  });

  const importMutation = useMutation({
    mutationFn: (payload: SupplementRowInput[]) => api.targetSupplements(targetId, payload),
    onSuccess: (outcome) => {
      setResult(outcome);
      setError(null);
      // A supplement changes the stored rows, so every read that depends on them
      // is refreshed rather than left showing a pre-import count.
      queryClient.invalidateQueries({ queryKey: ["target-reference", targetId] });
      queryClient.invalidateQueries({ queryKey: ["candidates", targetId] });
      queryClient.invalidateQueries({ queryKey: ["candidate-measurements", targetId] });
      queryClient.invalidateQueries({ queryKey: ["target-coverage", targetId] });
      queryClient.invalidateQueries({ queryKey: ["target-supplement-remarks", targetId] });
    },
    onError: (err) => setError((err as Error).message),
  });

  const problems = rows.map((row) => toRow(row));
  const blocked = problems.find((p) => p.problem);

  const set = (key: string, patch: Partial<DraftRow>) =>
    setRows((current) => current.map((row) => (row.key === key ? { ...row, ...patch } : row)));

  const submit = () => {
    const payload: SupplementRowInput[] = [];
    for (const attempt of problems) {
      if (attempt.problem) {
        setError(`Row ${problems.indexOf(attempt) + 1}: ${attempt.problem}`);
        return;
      }
      payload.push(attempt.row as SupplementRowInput);
    }
    setError(null);
    importMutation.mutate(payload);
  };

  const remarks = remarksQuery.data ?? [];
  const outcomeByIndex = new Map((result?.rows ?? []).map((row) => [row.index, row]));
  const stored = result
    ? result.measurements + result.remarks
    : 0;

  return (
    <Modal title={`Add rows to ${targetKey}`} onClose={onClose} wide>
      {error && (
        <div className="state-banner error" role="alert">
          <span>{error}</span>
        </div>
      )}

      {result && (
        <div className="state-banner" role="status">
          <span>
            {result.measurements} measurement(s) stored, {result.remarks} kept as a
            remark, {result.received - stored} refused.{" "}
            {result.updated > 0 &&
              `${result.updated} updated an existing row instead of duplicating it. `}
            {result.compounds_created > 0 &&
              `${result.compounds_created} new compound(s); `}
            {result.compounds_reused > 0 &&
              `${result.compounds_reused} already in the corpus.`}
          </span>
        </div>
      )}

      <p className="hint-note">
        Every row is a statement by you: it is stored with{" "}
        <span className="mono">user_curated</span> provenance, its note, and its document
        reference. Nothing here is added to a source's data, and a row without a public
        structure is kept as a remark — never drawn, never exported as a compound.
      </p>

      {rows.map((row, index) => {
        const outcome = outcomeByIndex.get(index);
        return (
          <div className="supplement-row" key={row.key}>
            <div className="supplement-row-head">
              <span className="fineprint">Row {index + 1}</span>
              {rows.length > 1 && (
                <button
                  className="btn btn-quiet"
                  onClick={() => setRows((current) => current.filter((r) => r.key !== row.key))}
                >
                  Remove
                </button>
              )}
            </div>

            <div className="supplement-grid">
              <label>
                <span className="input-label">Name in the source</span>
                <input
                  className="text-input"
                  value={row.name}
                  maxLength={300}
                  placeholder="e.g. Example 12 / compound 7"
                  onChange={(e) => set(row.key, { name: e.target.value })}
                />
              </label>
              <label>
                <span className="input-label">Public SMILES (optional)</span>
                <input
                  className="text-input"
                  value={row.smiles}
                  maxLength={4000}
                  placeholder="leave empty if the structure is not published"
                  onChange={(e) => set(row.key, { smiles: e.target.value })}
                />
              </label>
              <label>
                <span className="input-label">Endpoint</span>
                <input
                  className="text-input"
                  value={row.activityType}
                  maxLength={40}
                  placeholder="IC50"
                  onChange={(e) => set(row.key, { activityType: e.target.value })}
                />
              </label>
              <label>
                <span className="input-label">Relation</span>
                <select
                  className="select-input"
                  value={row.relation}
                  onChange={(e) => set(row.key, { relation: e.target.value })}
                >
                  <option value="=">=</option>
                  <option value="<">&lt;</option>
                  <option value="<=">&le;</option>
                  <option value=">">&gt;</option>
                  <option value=">=">&ge;</option>
                  <option value="~">~</option>
                </select>
              </label>
              <label>
                <span className="input-label">Value</span>
                <input
                  className="text-input"
                  type="number"
                  min="0"
                  step="any"
                  value={row.value}
                  onChange={(e) => set(row.key, { value: e.target.value })}
                />
              </label>
              <label>
                <span className="input-label">Unit</span>
                <input
                  className="text-input"
                  value={row.unit}
                  maxLength={20}
                  placeholder="nM"
                  onChange={(e) => set(row.key, { unit: e.target.value })}
                />
              </label>
              <label>
                <span className="input-label">DOI (optional)</span>
                <input
                  className="text-input"
                  value={row.doi}
                  maxLength={200}
                  onChange={(e) => set(row.key, { doi: e.target.value })}
                />
              </label>
              <label>
                <span className="input-label">PMID (optional)</span>
                <input
                  className="text-input"
                  value={row.pmid}
                  maxLength={20}
                  onChange={(e) => set(row.key, { pmid: e.target.value })}
                />
              </label>
              <label>
                <span className="input-label">Patent number (optional)</span>
                <input
                  className="text-input"
                  value={row.patentNumber}
                  maxLength={40}
                  placeholder="WO 2019/047734"
                  onChange={(e) => set(row.key, { patentNumber: e.target.value })}
                />
              </label>
            </div>

            <label>
              <span className="input-label">
                Note (required) — where you read it and what it says
              </span>
              <input
                className="text-input"
                value={row.note}
                maxLength={2000}
                placeholder="e.g. Table 2, human TSLP, fluorescent polarization assay"
                onChange={(e) => set(row.key, { note: e.target.value })}
              />
            </label>

            {outcome && (
              <div
                className={`supplement-outcome supplement-outcome-${outcome.status}`}
                role="status"
              >
                <span className="badge">
                  {outcome.status === "rejected"
                    ? "refused"
                    : outcome.status === "remark"
                      ? "kept as a remark"
                      : "stored"}
                </span>
                {outcome.status === "measurement" && (
                  <span>{activityClassLabel(outcome.activity_class ?? "not_applicable")}</span>
                )}
                {outcome.reused_compound && <span className="fineprint">existing compound</span>}
                <span className="fineprint">{outcome.reasons.join(" · ")}</span>
                {outcome.compound_id && (
                  <button
                    className="evidence-link"
                    onClick={() => {
                      onSelectCompound(outcome.compound_id as string);
                      onClose();
                    }}
                  >
                    Open evidence
                  </button>
                )}
              </div>
            )}
          </div>
        );
      })}

      <div className="modal-actions">
        <button className="btn btn-quiet" onClick={() => setRows((r) => [...r, emptyRow()])}>
          Add another row
        </button>
        <span className="spacer" />
        <button className="btn btn-quiet" onClick={onClose}>
          {result ? "Close" : "Cancel"}
        </button>
        <button
          className="btn btn-primary"
          disabled={importMutation.isPending || blocked !== undefined}
          title={blocked?.problem ?? EMPTY}
          onClick={submit}
        >
          {importMutation.isPending ? "Storing…" : "Store rows"}
        </button>
      </div>

      <div className="supplement-remarks">
        <h3 className="section-title">Stored remarks for this target</h3>
        {remarksQuery.isLoading && <span className="skeleton-note">Reading…</span>}
        {remarks.length === 0 && !remarksQuery.isLoading && (
          <span className="fineprint">
            No structure-less row is stored for this target yet.
          </span>
        )}
        {remarks.length > 0 && (
          <ul className="plain-list">
            {remarks.map((remark) => (
              <li key={remark.id}>
                <span className="mono">{remark.name}</span>
                {remark.value != null && (
                  <span>
                    {" "}
                    {remark.relation} {remark.value} {remark.unit} {remark.activity_type}
                  </span>
                )}
                {remark.doi && <span className="fineprint"> DOI {remark.doi}</span>}
                {remark.pmid && <span className="fineprint"> PMID {remark.pmid}</span>}
                {remark.patent_number && (
                  <span className="fineprint"> {remark.patent_number}</span>
                )}
                <div className="fineprint">{remark.note}</div>
              </li>
            ))}
          </ul>
        )}
      </div>
    </Modal>
  );
}
