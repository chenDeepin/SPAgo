import { useRef } from "react";
import { useVirtualizer } from "@tanstack/react-virtual";
import type { Candidate, CandidatePage } from "../api/types";
import { MoleculeImage } from "./MoleculeImage";
import { activityClassLabel } from "./ReferenceStrip";
import { evidenceClassLabel, modalityLabel } from "./TargetHeader";

interface CandidateTableProps {
  page: CandidatePage;
  selectedCompoundId: string | null;
  selectedIds: Set<string>;
  scopeLabel: string;
  onToggleSelection: (compoundId: string, checked: boolean) => void;
  onToggleSelectAll: (checked: boolean) => void;
  onClearSelection: () => void;
  onSelectCandidate: (compoundId: string) => void;
}

const ROW_HEIGHT = 96;
const COL_CHECK = 40;
const COL_STRUCTURE = 160;
const COL_ACTIVITY = 150;
const COL_MODALITY = 150;
const COL_EVIDENCE = 170;
const COL_PATENT = 170;
const MIN_TABLE_WIDTH =
  COL_CHECK +
  COL_STRUCTURE +
  260 +
  COL_ACTIVITY +
  COL_MODALITY +
  COL_EVIDENCE +
  COL_PATENT;

/** Virtualized candidate table for a target investigation.
 *
 * Deliberately similar to the patent compound table (same row height, same lazy
 * depiction) but it shows what is different about an open-database candidate:
 * the modality label, the evidence class, and the patent-linkage status. A
 * candidate with zero patent occurrences is a normal, selectable row — that is
 * the state the plan requires to stay usable rather than be discarded. */
export function CandidateTable({
  page,
  selectedCompoundId,
  selectedIds,
  scopeLabel,
  onToggleSelection,
  onToggleSelectAll,
  onClearSelection,
  onSelectCandidate,
}: CandidateTableProps) {
  // Rows kept visible although the filter excludes them (a saved or deep-linked
  // item): they are shown and labelled, never counted into `total` (D2).
  const pinnedCount = page.items.filter((row) => row.outside_filter).length;
  const scrollRef = useRef<HTMLDivElement>(null);
  const virtualizer = useVirtualizer({
    count: page.items.length,
    getScrollElement: () => scrollRef.current,
    estimateSize: () => ROW_HEIGHT,
    overscan: 6,
  });

  const loadedIds = page.items.map((r) => r.compound_id);
  const selectedLoaded = loadedIds.filter((id) => selectedIds.has(id)).length;
  const allSelected = loadedIds.length > 0 && selectedLoaded === loadedIds.length;

  return (
    <div className="table-panel">
      <div className="table-scroll" ref={scrollRef}>
        <div
          role="row"
          aria-rowindex={1}
          style={{
            display: "flex",
            minWidth: MIN_TABLE_WIDTH,
            alignItems: "center",
            height: "var(--head-h)",
            position: "sticky",
            top: 0,
            background: "var(--canvas)",
            borderBottom: "1px solid var(--border)",
            fontSize: 12,
            fontWeight: 600,
            color: "var(--text-2)",
            zIndex: 1,
          }}
        >
          <div style={{ flex: `0 0 ${COL_CHECK}px`, padding: "0 8px" }}>
            <input
              type="checkbox"
              aria-label="Select all loaded candidates"
              checked={allSelected}
              ref={(el) => {
                if (el) el.indeterminate = selectedLoaded > 0 && !allSelected;
              }}
              onChange={(e) => onToggleSelectAll(e.target.checked)}
            />
          </div>
          <div style={{ flex: `0 0 ${COL_STRUCTURE}px`, padding: "0 12px" }}>Structure</div>
          <div style={{ flex: 1 }}>Candidate</div>
          <div style={{ flex: `0 0 ${COL_ACTIVITY}px`, padding: "0 12px" }}>Activity</div>
          <div style={{ flex: `0 0 ${COL_MODALITY}px`, padding: "0 12px" }}>Modality</div>
          <div style={{ flex: `0 0 ${COL_EVIDENCE}px`, padding: "0 12px" }}>Evidence class</div>
          <div style={{ flex: `0 0 ${COL_PATENT}px`, padding: "0 12px" }}>Patent linkage</div>
        </div>

        <div
          role="table"
          aria-label={`Candidate compounds for ${scopeLabel}`}
          aria-rowcount={page.total}
          style={{ position: "relative", minWidth: MIN_TABLE_WIDTH, height: virtualizer.getTotalSize() }}
        >
          {virtualizer.getVirtualItems().map((virtualRow) => {
            const row: Candidate = page.items[virtualRow.index];
            const selected = row.compound_id === selectedCompoundId;
            const checked = selectedIds.has(row.compound_id);
            return (
              <div
                key={row.compound_id}
                role="row"
                aria-rowindex={virtualRow.index + 2}
                aria-selected={selected}
                tabIndex={0}
                data-index={virtualRow.index}
                ref={virtualizer.measureElement}
                onClick={() => onSelectCandidate(row.compound_id)}
                onKeyDown={(e) => {
                  if (e.key === "Enter" || e.key === " ") {
                    e.preventDefault();
                    onSelectCandidate(row.compound_id);
                  }
                }}
                style={{
                  position: "absolute",
                  top: 0,
                  left: 0,
                  width: "100%",
                  transform: `translateY(${virtualRow.start}px)`,
                  display: "flex",
                  alignItems: "center",
                  minHeight: ROW_HEIGHT,
                  borderBottom: "1px solid var(--border)",
                  padding: "8px 0",
                  background: selected ? "var(--accent-bg)" : undefined,
                  cursor: "pointer",
                }}
              >
                <div style={{ flex: `0 0 ${COL_CHECK}px`, padding: "0 8px" }}>
                  <input
                    type="checkbox"
                    aria-label={`Select candidate ${row.inchikey}`}
                    checked={checked}
                    onClick={(e) => e.stopPropagation()}
                    onChange={(e) => onToggleSelection(row.compound_id, e.target.checked)}
                  />
                </div>
                <div style={{ flex: `0 0 ${COL_STRUCTURE}px`, padding: "0 12px" }}>
                  <span className="structure-btn" aria-label={`Structure for ${row.inchikey}`}>
                    <MoleculeImage compoundId={row.compound_id} />
                  </span>
                </div>
                <div style={{ flex: 1, minWidth: 0, padding: "0 12px" }}>
                  <div className="mono" title={row.inchikey}>
                    {row.inchikey.slice(0, 14)}…
                  </div>
                  <div style={{ fontSize: 12, color: "var(--text-2)", marginTop: 2 }}>
                    {row.molecular_formula ?? "formula not provided"}
                    {row.molecular_weight != null && ` · ${row.molecular_weight} Da`}
                    {` · ${row.measurements} measurement${row.measurements === 1 ? "" : "s"}`}
                  </div>
                  <div style={{ fontSize: 11, color: "var(--text-2)", marginTop: 2 }}>
                    from {row.source_name} · {row.source_record_id}
                  </div>
                  {row.outside_filter && (
                    <div
                      className="scope-note"
                      data-outside-filter="true"
                      style={{ fontSize: 11, marginTop: 2 }}
                    >
                      outside the current filter — shown because it is saved or selected
                    </div>
                  )}
                </div>
                <div style={{ flex: `0 0 ${COL_ACTIVITY}px`, padding: "0 12px" }}>
                  <span className={`badge badge-activity-${row.activity_class}`}>
                    {activityClassLabel(row.activity_class)}
                  </span>
                  <div style={{ fontSize: 11, color: "var(--text-2)", marginTop: 2 }}>
                    {row.potency_label ?? "no potency value for this threshold"}
                  </div>
                </div>
                <div style={{ flex: `0 0 ${COL_MODALITY}px`, padding: "0 12px" }}>
                  <span className={`badge badge-${row.modality}`}>{modalityLabel(row.modality)}</span>
                  <div style={{ fontSize: 11, color: "var(--text-2)", marginTop: 2 }}>
                    {row.modality_source ?? ""}
                    {row.modality_rule ? ` · ${row.modality_rule.split(";")[0]}` : ""}
                  </div>
                </div>
                <div style={{ flex: `0 0 ${COL_EVIDENCE}px`, padding: "0 12px", fontSize: 12 }}>
                  {evidenceClassLabel(row.evidence_class)}
                </div>
                <div style={{ flex: `0 0 ${COL_PATENT}px`, padding: "0 12px", fontSize: 12 }}>
                  {row.patent_occurrences > 0 ? (
                    <span title={row.patent_labels.join("; ")}>
                      {row.patent_occurrences} occurrence
                      {row.patent_occurrences === 1 ? "" : "s"}
                    </span>
                  ) : (
                    <span className="not-provided">no patent mapping</span>
                  )}
                  {/* A patent number the *source* declares is a different fact
                      from an occurrence in the loaded corpus, so it is shown as
                      such and never merged into the count above (AGENTS.md §10). */}
                  {row.source_declared_patents.length > 0 && (
                    <div className="fineprint" style={{ marginTop: 2 }}>
                      source declares {row.source_declared_patents.join(", ")}
                    </div>
                  )}
                </div>
              </div>
            );
          })}
        </div>
      </div>
      <div className="table-footer">
        <span>
          {page.total === 0
            ? "0 candidates"
            : `${page.offset + 1}–${page.offset + page.items.length} of ${page.total}`}
          {/* Pinned rows are outside the filter by definition, so they are not
              part of "of N". Saying so keeps the two numbers from contradicting:
              a saved item is visible, and it is marked as an outsider (D2). */}
          {pinnedCount > 0 &&
            ` · ${pinnedCount} outside the current filter (shown, not counted)`}
        </span>
        <span className="fineprint">
          Showing {page.default_filter}. Potency classes are computed against{" "}
          {page.policy ? page.policy.threshold_label : "the deployment threshold"} (
          {page.policy ? page.policy.version : "policy unstated"}). Classification and evidence
          labels are deterministic; a candidate without a patent mapping is still usable and
          savable.
        </span>
        {selectedIds.size > 0 && (
          <span>
            {selectedIds.size} selected for save
            <button className="show-all-occ" style={{ marginLeft: 8 }} onClick={onClearSelection}>
              Clear selection
            </button>
          </span>
        )}
      </div>
    </div>
  );
}
