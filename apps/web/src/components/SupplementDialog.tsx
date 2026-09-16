import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api } from "../api/client";
import type {
  SupplementBundleInput,
  SupplementImport,
  SupplementImportReport,
  SupplementRowInput,
} from "../api/types";
import { Modal } from "./Modal";
import { activityClassLabel } from "./ReferenceStrip";
import { TakeBackControl } from "./TakeBackControl";

interface SupplementDialogProps {
  targetId: string;
  targetKey: string;
  onClose: () => void;
  /** Opens a stored compound's evidence in the existing inspector. */
  onSelectCompound: (compoundId: string) => void;
  /** Which pane opens first: a hand-typed row, or a whole bundle (B-25). */
  initialMode?: SupplementDialogMode;
}

/** The two ways rows enter a target, offered in one dialog rather than two. */
export type SupplementDialogMode = "rows" | "bundle";

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
  initialMode = "rows",
}: SupplementDialogProps) {
  const queryClient = useQueryClient();
  const [mode, setMode] = useState<SupplementDialogMode>(initialMode);
  const [rows, setRows] = useState<DraftRow[]>(() => [emptyRow()]);
  const [result, setResult] = useState<SupplementImport | null>(null);
  const [error, setError] = useState<string | null>(null);

  const remarksQuery = useQuery({
    queryKey: ["target-supplement-remarks", targetId],
    queryFn: ({ signal }) => api.targetSupplementRemarks(targetId, signal),
  });

  const withdrawnQuery = useQuery({
    queryKey: ["target-withdrawn-supplements", targetId],
    queryFn: ({ signal }) => api.targetWithdrawnSupplements(targetId, signal),
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

  // One withdraw action for the whole dialog: every read that counts the row is
  // refreshed, so a taken-back row cannot linger in a count (defect D3).
  const withdrawMutation = useMutation({
    mutationFn: ({ recordId, reason }: { recordId: string; reason: string }) =>
      api.withdrawTargetSupplement(targetId, recordId, reason),
    onSuccess: () => {
      setError(null);
      queryClient.invalidateQueries({ queryKey: ["target-reference", targetId] });
      queryClient.invalidateQueries({ queryKey: ["candidates", targetId] });
      queryClient.invalidateQueries({ queryKey: ["candidate-measurements", targetId] });
      queryClient.invalidateQueries({ queryKey: ["target-coverage", targetId] });
      queryClient.invalidateQueries({ queryKey: ["target-supplement-remarks", targetId] });
      queryClient.invalidateQueries({ queryKey: ["target-withdrawn-supplements", targetId] });
    },
    onError: (err) => setError((err as Error).message),
  });

  const withdraw = (recordId: string, reason: string) =>
    withdrawMutation.mutateAsync({ recordId, reason }).then(() => undefined);

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
  const withdrawn = withdrawnQuery.data ?? [];
  const outcomeByIndex = new Map((result?.rows ?? []).map((row) => [row.index, row]));
  const stored = result
    ? result.measurements + result.remarks
    : 0;

  return (
    <Modal title={`Add rows to ${targetKey}`} onClose={onClose} wide>
      <div role="tablist" aria-label="How the rows arrive" className="inspector-tabs">
        <button
          role="tab"
          aria-selected={mode === "rows"}
          className="inspector-tab"
          onClick={() => setMode("rows")}
        >
          One row by hand
        </button>
        <button
          role="tab"
          aria-selected={mode === "bundle"}
          className="inspector-tab"
          onClick={() => setMode("bundle")}
        >
          A set of rows (JSON bundle)
        </button>
      </div>

      {error && (
        <div className="state-banner error" role="alert">
          <span>{error}</span>
        </div>
      )}

      {/* B-25: a bundle is an artifact, not a paste box. Its own pane because the
          questions are different: a hand-typed row asks "what do you know", a bundle
          asks "who produced this, what was searched, and has a person read it". */}
      {mode === "bundle" && (
        <BundlePane
          targetId={targetId}
          onSelectCompound={onSelectCompound}
          onClose={onClose}
          onError={setError}
        />
      )}

      {mode === "rows" && (
        <>
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
                {outcome.record_id && outcome.status !== "rejected" && (
                  <TakeBackControl
                    what="This row"
                    pending={withdrawMutation.isPending}
                    onWithdraw={(why) =>
                      withdraw(outcome.record_id as string, why).catch(() => undefined)
                    }
                  />
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
              <li key={remark.id} className={remark.retracted_at ? "withdrawn-row" : undefined}>
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
                {remark.retracted_at ? (
                  <div className="withdrawn-reason">
                    Taken back {new Date(remark.retracted_at).toLocaleString()} —{" "}
                    {remark.retracted_reason ?? "no reason recorded"}
                  </div>
                ) : (
                  <TakeBackControl
                    what="This remark"
                    pending={withdrawMutation.isPending}
                    onWithdraw={(reason) =>
                      withdraw(remark.source_record_id, reason).catch(() => undefined)
                    }
                  />
                )}
              </li>
            ))}
          </ul>
        )}

        {/* Rows the user added by hand and later took back. Both kinds in one list:
            the question "what did I take back, and why" does not depend on whether
            the row carried a structure (defect D3). */}
        <h3 className="section-title">Taken back by you</h3>
        {withdrawnQuery.isLoading && <span className="skeleton-note">Reading…</span>}
        {!withdrawnQuery.isLoading && withdrawn.length === 0 && (
          <span className="fineprint">Nothing has been taken back for this target.</span>
        )}
        {withdrawn.length > 0 && (
          <ul className="plain-list">
            {withdrawn.map((row) => (
              <li key={`${row.kind}-${row.record_id}`} className="withdrawn-row">
                <span className="mono">{row.name || row.record_id}</span>
                <span className="badge">{row.kind === "remark" ? "remark" : "measurement"}</span>
                {row.value != null && (
                  <span>
                    {" "}
                    {row.relation} {row.value} {row.unit} {row.activity_type}
                  </span>
                )}
                <div className="withdrawn-reason">
                  Taken back {new Date(row.retracted_at).toLocaleString()} —{" "}
                  {row.retracted_reason ?? "no reason recorded"}
                  {row.candidate_retracted && " · the compound left the candidate list"}
                </div>
                <div className="fineprint">
                  The row is still stored: re-adding it restores it instead of creating a
                  second copy.
                </div>
              </li>
            ))}
          </ul>
        )}
      </div>
        </>
      )}
    </Modal>
  );
}

// --- B-25: a set of rows arrives as one artifact, and a person admits it ----------

/** How many records one bundle may carry: the server's bound, stated up front.
 * A file over the bound is refused rather than silently reduced. */
const MAX_BUNDLE_RECORDS = 200;

const BUNDLE_TEMPLATE = `{
  "bundle_version": 1,
  "produced_by": "who or what produced these rows",
  "produced_by_kind": "human",
  "searched": "what was searched, so a reader can re-find the rows",
  "generated_at": "2026-09-16T09:00:00Z",
  "uniprot": "P12345",
  "records": [
    {
      "name": "compound 7",
      "note": "Table 2 of the paper; IC50 against the human target",
      "smiles": "Cc1ccccc1",
      "activity_type": "IC50",
      "value": 4.0,
      "unit": "nM",
      "doi": "10.1021/acs.jmedchem.0c00001"
    }
  ]
}`;

/** Read the pasted text as a bundle without pretending to be the contract.
 *
 * The envelope checks here exist so a producer reads a plain sentence about a missing
 * field instead of a raw validation payload; the server re-validates every row and its
 * answer is what counts. Nothing is normalized on the client: the file is sent as
 * written, so the stored report describes the artifact that actually arrived. */
function parseBundle(text: string): { bundle?: SupplementBundleInput; problem?: string } {
  let parsed: unknown;
  try {
    parsed = JSON.parse(text);
  } catch (err) {
    return { problem: `This is not valid JSON: ${(err as Error).message}` };
  }
  if (Array.isArray(parsed)) {
    return {
      problem:
        "A bundle is a JSON object, not a list: it must state who produced the rows and what was searched, so the rows stay traceable.",
    };
  }
  if (parsed === null || typeof parsed !== "object") {
    return { problem: "A bundle is a JSON object with produced_by, produced_by_kind, searched and records." };
  }
  const obj = parsed as Record<string, unknown>;
  const textFields: [string, string][] = [
    ["produced_by", "who or what produced these rows"],
    ["searched", "what was searched, in your own words"],
  ];
  for (const [field, what] of textFields) {
    if (typeof obj[field] !== "string" || !(obj[field] as string).trim()) {
      return { problem: `The bundle must state ${field}: ${what}.` };
    }
  }
  const kind = obj["produced_by_kind"];
  if (kind !== "human" && kind !== "agent" && kind !== "external") {
    return {
      problem:
        'produced_by_kind must be "human" (your own reading), "agent" (a model proposed the rows) or "external" (a script or another tool wrote the file).',
    };
  }
  const records = obj["records"];
  if (!Array.isArray(records) || records.length === 0) {
    return { problem: "records must be a non-empty list of row objects." };
  }
  if (records.length > MAX_BUNDLE_RECORDS) {
    return {
      problem: `records carries ${records.length} rows; one bundle may carry at most ${MAX_BUNDLE_RECORDS}. Split the file rather than have rows silently dropped.`,
    };
  }
  return { bundle: obj as unknown as SupplementBundleInput };
}

const PRODUCER_KIND_LABEL: Record<string, string> = {
  human: "a person's own reading",
  agent: "a model proposed the rows",
  external: "a script or another tool wrote the file",
};

interface BundlePaneProps {
  targetId: string;
  onSelectCompound: (compoundId: string) => void;
  onClose: () => void;
  onError: (message: string | null) => void;
}

/** The bundle pane: paste or load a file, read what it refused, review the rows. */
function BundlePane({ targetId, onSelectCompound, onClose, onError }: BundlePaneProps) {
  const queryClient = useQueryClient();
  const [text, setText] = useState("");
  const [imported, setImported] = useState<SupplementImportReport | null>(null);
  const [confirmation, setConfirmation] = useState<string | null>(null);

  const importsQuery = useQuery({
    queryKey: ["supplement-imports", targetId],
    queryFn: ({ signal }) => api.supplementImports(targetId, signal),
  });

  /** Every read that counts a stored row, refreshed after an import or a review. */
  const refreshStoredRows = () => {
    queryClient.invalidateQueries({ queryKey: ["target-reference", targetId] });
    queryClient.invalidateQueries({ queryKey: ["candidates", targetId] });
    queryClient.invalidateQueries({ queryKey: ["candidate-measurements", targetId] });
    queryClient.invalidateQueries({ queryKey: ["target-coverage", targetId] });
    queryClient.invalidateQueries({ queryKey: ["target-supplement-remarks", targetId] });
    queryClient.invalidateQueries({ queryKey: ["target-withdrawn-supplements", targetId] });
    queryClient.invalidateQueries({ queryKey: ["supplement-imports", targetId] });
  };

  const importMutation = useMutation({
    mutationFn: (bundle: SupplementBundleInput) => api.importSupplementBundle(targetId, bundle),
    onSuccess: (outcome) => {
      setImported(outcome.report);
      setConfirmation(null);
      onError(null);
      refreshStoredRows();
    },
    onError: (err) => onError((err as Error).message),
  });

  const confirmMutation = useMutation({
    mutationFn: (importId: string) => api.confirmSupplementImport(targetId, importId),
    onSuccess: (outcome) => {
      setConfirmation(
        outcome.already_confirmed
          ? "This import had already been confirmed; nothing was changed twice."
          : `${outcome.rows} row(s) admitted to this investigation: the rows are yours now, and ${outcome.candidates_created} compound(s) joined the candidate list.`,
      );
      onError(null);
      refreshStoredRows();
    },
    onError: (err) => onError((err as Error).message),
  });

  const withdrawMutation = useMutation({
    mutationFn: ({ recordId, reason }: { recordId: string; reason: string }) =>
      api.withdrawTargetSupplement(targetId, recordId, reason),
    onSuccess: () => {
      onError(null);
      refreshStoredRows();
    },
    onError: (err) => onError((err as Error).message),
  });

  const parsed = text.trim() ? parseBundle(text) : {};
  const problem = text.trim() ? parsed.problem : undefined;

  const loadFile = (file: File | undefined) => {
    if (!file) return;
    const reader = new FileReader();
    reader.onload = () => setText(String(reader.result ?? ""));
    reader.onerror = () => onError("The file could not be read.");
    reader.readAsText(file);
  };

  const reports = importsQuery.data ?? [];
  const unreviewed = reports.filter((report) => report.awaiting_review).length;

  return (
    <div className="bundle-pane">
      <p className="hint-note">
        A bundle is a JSON file of rows plus the run that produced it:{" "}
        <span className="mono">produced_by</span>,{" "}
        <span className="mono">produced_by_kind</span> and{" "}
        <span className="mono">searched</span> travel with the rows, so a reader can
        re-find them and see where they came from. A row SPAgo cannot store is refused
        with its reasons — the rest of the file still arrives.
      </p>
      <p className="hint-note">
        <strong>What a bundle is depends on who produced it.</strong> A file you wrote is
        your own statement (<span className="mono">user_curated</span>). A file an agent
        or a script produced is a <em>proposal</em>: its rows are stored, readable and
        counted separately, and they join no verdict, candidate list, export or summary
        until you read them and confirm the import.
      </p>

      <label className="input-label" htmlFor="bundle-json">
        Bundle JSON (paste it, or load the file)
      </label>
      <textarea
        id="bundle-json"
        className="text-input bundle-textarea"
        value={text}
        spellCheck={false}
        placeholder={BUNDLE_TEMPLATE}
        onChange={(e) => setText(e.target.value)}
      />
      <div className="bundle-actions">
        <input
          className="file-input"
          type="file"
          accept=".json,application/json"
          aria-label="Load a bundle file"
          onChange={(e) => loadFile(e.target.files?.[0])}
        />
        <button className="btn btn-quiet" disabled={!text} onClick={() => setText("")}>
          Clear
        </button>
        <button
          className="btn btn-quiet"
          disabled={Boolean(text)}
          onClick={() => setText(BUNDLE_TEMPLATE)}
        >
          Show the shape
        </button>
      </div>

      {problem && (
        <div className="state-banner error" role="alert">
          <span>{problem}</span>
        </div>
      )}

      <div className="modal-actions">
        <span className="fineprint">
          {text.trim() && !problem && parsed.bundle
            ? `${(parsed.bundle.records ?? []).length} row(s), produced by ${parsed.bundle.produced_by_kind}`
            : "Nothing to import yet."}
        </span>
        <span className="spacer" />
        <button className="btn btn-quiet" onClick={onClose}>
          Close
        </button>
        <button
          className="btn btn-primary"
          disabled={importMutation.isPending || !parsed.bundle}
          onClick={() => parsed.bundle && importMutation.mutate(parsed.bundle)}
        >
          {importMutation.isPending ? "Importing…" : "Import bundle"}
        </button>
      </div>

      {imported && (
        <BundleReport
          report={imported}
          fresh
          confirming={confirmMutation.isPending}
          withdrawing={withdrawMutation.isPending}
          onConfirm={() => confirmMutation.mutate(imported.id)}
          onWithdraw={(recordId, reason) =>
            withdrawMutation.mutateAsync({ recordId, reason }).then(() => undefined)
          }
          onSelectCompound={onSelectCompound}
        />
      )}

      {confirmation && (
        <div className="state-banner" role="status">
          <span>{confirmation}</span>
        </div>
      )}

      <h3 className="section-title">
        Bundles imported for this target
        {unreviewed > 0 && <span className="badge">{unreviewed} awaiting your review</span>}
      </h3>
      {importsQuery.isLoading && <span className="skeleton-note">Reading…</span>}
      {importsQuery.isError && (
        <span className="fineprint">
          The import history could not be read. That is a service failure, not a statement
          about what was imported.
        </span>
      )}
      {!importsQuery.isLoading && !importsQuery.isError && reports.length === 0 && (
        <span className="fineprint">No bundle has been imported for this target yet.</span>
      )}
      {reports
        // The run that just arrived is rendered above with its review control; the list
        // below is the persisted history, so the same import is not shown twice.
        .filter((report) => report.id !== imported?.id)
        .map((report) => (
          <BundleReport
            key={report.id}
            report={report}
            confirming={confirmMutation.isPending}
            withdrawing={withdrawMutation.isPending}
            onConfirm={() => confirmMutation.mutate(report.id)}
            onWithdraw={(recordId, reason) =>
              withdrawMutation.mutateAsync({ recordId, reason }).then(() => undefined)
            }
            onSelectCompound={onSelectCompound}
          />
        ))}
    </div>
  );
}

interface BundleReportProps {
  report: SupplementImportReport;
  fresh?: boolean;
  confirming: boolean;
  withdrawing: boolean;
  onConfirm: () => void;
  onWithdraw: (recordId: string, reason: string) => Promise<void>;
  onSelectCompound: (compoundId: string) => void;
}

/** One import: who produced it, what was answered per row, and what is stored now. */
function BundleReport({
  report,
  fresh = false,
  confirming,
  withdrawing,
  onConfirm,
  onWithdraw,
  onSelectCompound,
}: BundleReportProps) {
  const refused = report.rows.filter((row) => row.status === "rejected");
  return (
    <div className={`bundle-report${fresh ? " bundle-report-fresh" : ""}`}>
      <div className="bundle-report-head">
        <span className="badge">{PRODUCER_KIND_LABEL[report.produced_by_kind] ?? report.produced_by_kind}</span>
        <span className="mono">{report.produced_by}</span>
        {report.awaiting_review ? (
          <span className="badge badge-warn">not yet reviewed</span>
        ) : (
          <span className="badge">
            {report.confirmed_at ? "confirmed" : "your own rows"}
          </span>
        )}
        {report.repeated_of && <span className="fineprint">the same file was imported before</span>}
      </div>
      <div className="fineprint">
        Searched for: {report.searched}
        {report.generated_at ? ` · stated as generated ${report.generated_at}` : ""}
        {report.submitted_by ? ` · imported by ${report.submitted_by}` : ""}
      </div>
      {report.confirmed_at && (
        <div className="fineprint">
          Confirmed as part of this investigation
          {report.confirmed_by ? ` by ${report.confirmed_by}` : ""} on{" "}
          {new Date(report.confirmed_at).toLocaleString()}.
        </div>
      )}
      <div className="bundle-counts">
        <span>
          <strong>{report.measurements}</strong> stored as measurements
        </span>
        <span>
          <strong>{report.remarks}</strong> kept as remarks (no public structure)
        </span>
        {report.rejected > 0 && (
          <span className="reference-warn">
            <strong>{report.rejected}</strong> refused with reasons
          </span>
        )}
        {report.updated_rows > 0 && <span>{report.updated_rows} updated an existing row</span>}
        {report.compounds_created + report.compounds_reused > 0 && (
          <span>
            {report.compounds_created} new compound(s), {report.compounds_reused} already in
            the corpus
          </span>
        )}
      </div>

      {refused.length > 0 && (
        <ul className="plain-list bundle-refusals">
          {refused.map((row) => (
            <li key={`refused-${row.index}`}>
              <span className="mono">
                row {row.index + 1}
                {row.name ? `: ${row.name}` : ""}
              </span>
              <div className="fineprint">{row.reasons.join(" · ")}</div>
            </li>
          ))}
        </ul>
      )}

      {report.stored.length > 0 && (
        <ul className="plain-list">
          {report.stored.map((row) => (
            <li key={row.record_id} className={row.live ? undefined : "withdrawn-row"}>
              <span className="mono">{row.name || row.record_id}</span>
              <span className="badge">{row.kind === "remark" ? "remark" : "measurement"}</span>
              {row.value != null && (
                <span>
                  {" "}
                  {row.relation} {row.value} {row.unit} {row.activity_type} ·{" "}
                  {activityClassLabel(row.activity_class ?? "not_applicable")}
                </span>
              )}
              {row.doi && <span className="fineprint"> DOI {row.doi}</span>}
              {row.pmid && <span className="fineprint"> PMID {row.pmid}</span>}
              {row.patent_number && <span className="fineprint"> {row.patent_number}</span>}
              <div className="fineprint">{row.note}</div>
              {row.live ? (
                <>
                  {row.compound_id && (
                    <button
                      className="evidence-link"
                      onClick={() => onSelectCompound(row.compound_id as string)}
                    >
                      Open evidence
                    </button>
                  )}
                  <TakeBackControl
                    what="This row"
                    pending={withdrawing}
                    onWithdraw={(why) => onWithdraw(row.record_id, why).catch(() => undefined)}
                  />
                </>
              ) : (
                <div className="withdrawn-reason">
                  Taken back {row.retracted_at ? new Date(row.retracted_at).toLocaleString() : ""}{" "}
                  — {row.retracted_reason ?? "no reason recorded"}
                </div>
              )}
            </li>
          ))}
        </ul>
      )}

      {report.awaiting_review && (
        <div className="bundle-review">
          <span className="fineprint">
            Nothing here is part of this investigation yet: these rows are outside the
            counts, the candidate list, the exports and any summary until you confirm them.
          </span>
          <button className="btn btn-primary" disabled={confirming} onClick={onConfirm}>
            {confirming ? "Confirming…" : "I have read these rows"}
          </button>
        </div>
      )}
    </div>
  );
}
