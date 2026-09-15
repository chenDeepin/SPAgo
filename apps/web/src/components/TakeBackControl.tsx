import { useState } from "react";

interface TakeBackControlProps {
  /** The text of the quiet action, e.g. "Take back". */
  label?: string;
  /** What the row is, for the confirmation sentence. */
  what: string;
  /** The reason is required: a withdrawal without one is a silent edit. */
  onWithdraw: (reason: string) => void | Promise<void>;
  pending?: boolean;
}

/** Take a hand-added row back, with a reason (ONLINE-07 / defect D3).
 *
 * One control for every surface that can withdraw a row — the supplement dialog
 * and the candidate's measurement table — so the action has a single owner and a
 * single required field (AGENTS.md §18). It never deletes: the row stays readable
 * with this reason, and the reference verdict counts it as withdrawn.
 */
export function TakeBackControl({ label = "Take back", what, onWithdraw, pending }: TakeBackControlProps) {
  const [open, setOpen] = useState(false);
  const [reason, setReason] = useState("");

  if (!open) {
    return (
      <button className="btn btn-quiet" onClick={() => setOpen(true)}>
        {label}
      </button>
    );
  }

  const trimmed = reason.trim();
  return (
    <div className="take-back">
      <label>
        <span className="input-label">Why this row is being taken back (required)</span>
        <input
          className="text-input"
          value={reason}
          maxLength={300}
          autoFocus
          placeholder="e.g. typed by mistake during acceptance"
          onChange={(e) => setReason(e.target.value)}
        />
      </label>
      <div className="take-back-actions">
        <span className="fineprint">
          {what} stays stored and readable, marked as taken back with this reason.
        </span>
        <span className="spacer" />
        <button
          className="btn btn-quiet"
          onClick={() => {
            setOpen(false);
            setReason("");
          }}
        >
          Cancel
        </button>
        <button
          className="btn btn-primary"
          disabled={!trimmed || pending}
          title={trimmed ? undefined : "a reason is required"}
          onClick={() => void onWithdraw(trimmed)}
        >
          {pending ? "Taking back…" : "Take back row"}
        </button>
      </div>
    </div>
  );
}
