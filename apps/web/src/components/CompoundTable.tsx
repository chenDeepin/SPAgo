import { useMemo, useRef, useState } from "react";
import { useVirtualizer } from "@tanstack/react-virtual";
import type { CompoundPage } from "../api/types";
import { MoleculeImage } from "./MoleculeImage";

interface CompoundTableProps {
  page: CompoundPage;
  selectedCompoundId: string | null;
  selectedIds: Set<string>;
  scopeLabel: string;
  sarMode: boolean;
  onToggleSelection: (compoundId: string, checked: boolean) => void;
  onToggleSelectAll: (checked: boolean) => void;
  onClearSelection: () => void;
  onOpenStructure: (compoundId: string) => void;
  onSelectCompound: (compoundId: string) => void;
}

const LABEL_COLLAPSE = 3;
const ROW_HEIGHT = 96;

const COL_CHECK = 40;
const COL_STRUCTURE = 160;
const COL_LABELS = 190;
const COL_ACTIVITY = 130;
const COL_EVIDENCE = 120;

function activityText(a: {
  standard_type: string;
  relation: string;
  value: number;
  unit: string;
}): string {
  const value =
    a.value >= 1000 ? `${(a.value / 1000).toFixed(a.value % 1000 === 0 ? 0 : 1)} µM` : `${a.value} nM`;
  return `${a.standard_type} ${a.relation} ${value}`;
}

/** Virtualized compound table. Checkbox selection and row inspection are
 * separate concerns (design contract 3). SAR mode groups rows by Murcko
 * scaffold (M3): same-scaffold rows sort together and show their scaffold.
 * Activity values come from typed measurements; "none shown" never means
 * "inactive" (design doc M3 status table). */
export function CompoundTable({
  page,
  selectedCompoundId,
  selectedIds,
  scopeLabel,
  sarMode,
  onToggleSelection,
  onToggleSelectAll,
  onClearSelection,
  onOpenStructure,
  onSelectCompound,
}: CompoundTableProps) {
  const scrollRef = useRef<HTMLDivElement>(null);
  const [expanded, setExpanded] = useState<Record<string, boolean>>({});

  const items = useMemo(() => {
    if (!sarMode) return page.items;
    return [...page.items].sort(
      (a, b) =>
        (a.compound.scaffold ?? "\uffff").localeCompare(b.compound.scaffold ?? "\uffff") ||
        a.compound.inchikey.localeCompare(b.compound.inchikey),
    );
  }, [page.items, sarMode]);

  const virtualizer = useVirtualizer({
    count: items.length,
    getScrollElement: () => scrollRef.current,
    estimateSize: () => ROW_HEIGHT,
    overscan: 6,
  });

  const loadedIds = items.map((r) => r.compound.id);
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
              aria-label="Select all loaded compounds"
              checked={allSelected}
              ref={(el) => {
                if (el) el.indeterminate = selectedLoaded > 0 && !allSelected;
              }}
              onChange={(e) => onToggleSelectAll(e.target.checked)}
            />
          </div>
          <div style={{ flex: `0 0 ${COL_STRUCTURE}px`, padding: "0 12px" }}>Structure</div>
          <div style={{ flex: 1 }}>Compound</div>
          <div style={{ flex: `0 0 ${COL_LABELS}px`, padding: "0 12px" }}>Patent label</div>
          <div style={{ flex: `0 0 ${COL_ACTIVITY}px`, padding: "0 12px" }}>Activity</div>
          <div style={{ flex: `0 0 ${COL_EVIDENCE}px`, padding: "0 12px" }}>Evidence</div>
        </div>

        <div
          role="table"
          aria-label={`Compounds in ${scopeLabel}`}
          aria-rowcount={page.total}
          style={{ position: "relative", height: virtualizer.getTotalSize() }}
        >
          {virtualizer.getVirtualItems().map((virtualRow) => {
            const row = items[virtualRow.index];
            const compound = row.compound;
            const selected = compound.id === selectedCompoundId;
            const checked = selectedIds.has(compound.id);
            const showAll = expanded[compound.id] ?? false;
            const visibleMentions = showAll ? row.mentions : row.mentions.slice(0, LABEL_COLLAPSE);
            const prev = virtualRow.index > 0 ? items[virtualRow.index - 1] : null;
            const scaffoldBreak =
              sarMode && compound.scaffold && prev?.compound.scaffold !== compound.scaffold;
            return (
              <div
                key={compound.id}
                role="row"
                aria-rowindex={virtualRow.index + 2}
                aria-selected={selected}
                tabIndex={0}
                data-index={virtualRow.index}
                ref={virtualizer.measureElement}
                onClick={() => onSelectCompound(compound.id)}
                onKeyDown={(e) => {
                  if (e.key === "Enter" || e.key === " ") {
                    e.preventDefault();
                    onSelectCompound(compound.id);
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
                  borderTop:
                    scaffoldBreak && virtualRow.index > 0 ? "2px solid var(--border)" : undefined,
                  padding: "8px 0",
                  background: selected ? "var(--accent-bg)" : undefined,
                  cursor: "pointer",
                }}
              >
                <div style={{ flex: `0 0 ${COL_CHECK}px`, padding: "0 8px" }}>
                  <input
                    type="checkbox"
                    aria-label={`Select compound ${compound.inchikey}`}
                    checked={checked}
                    onClick={(e) => e.stopPropagation()}
                    onChange={(e) => onToggleSelection(compound.id, e.target.checked)}
                  />
                </div>
                <div style={{ flex: `0 0 ${COL_STRUCTURE}px`, padding: "0 12px" }}>
                  <button
                    className="structure-btn"
                    onClick={(e) => {
                      e.stopPropagation();
                      onOpenStructure(compound.id);
                    }}
                    aria-label={`Open larger structure preview for ${compound.inchikey}`}
                    title="Open larger preview"
                  >
                    <MoleculeImage compoundId={compound.id} />
                  </button>
                </div>
                <div style={{ flex: 1, minWidth: 0, padding: "0 12px" }}>
                  <div className="mono" title={compound.inchikey}>
                    {compound.inchikey.slice(0, 14)}…
                  </div>
                  <div style={{ fontSize: 12, color: "var(--text-2)", marginTop: 2 }}>
                    {compound.molecular_formula ?? "formula not provided"}
                    {compound.molecular_weight != null && ` · ${compound.molecular_weight} Da`}
                    {compound.has_stereo && " · stereo specified"}
                    {compound.is_multi_component && " · multi-component"}
                  </div>
                  {sarMode && (
                    <div
                      className="mono"
                      style={{
                        fontSize: 11,
                        color: "var(--text-2)",
                        marginTop: 2,
                        overflowWrap: "anywhere",
                      }}
                      title={compound.scaffold ?? ""}
                    >
                      scaffold: {compound.scaffold ?? "not provided"}
                    </div>
                  )}
                </div>
                <div
                  className="cell-labels"
                  style={{ flex: `0 0 ${COL_LABELS}px`, minWidth: 0, padding: "0 12px" }}
                >
                  {visibleMentions.map((m) => (
                    <span className="occ" key={m.id}>
                      {m.patent_label ?? <span className="not-provided">label not provided</span>}{" "}
                      <span className="doc">· {m.publication_number}</span>
                    </span>
                  ))}
                  {row.mentions.length > visibleMentions.length && (
                    <button
                      className="show-all-occ"
                      onClick={(e) => {
                        e.stopPropagation();
                        setExpanded((prev) => ({ ...prev, [compound.id]: true }));
                      }}
                    >
                      Show all {row.mentions.length} occurrences
                    </button>
                  )}
                  {row.mentions.length === 0 && <span className="not-provided">Not provided</span>}
                </div>
                <div style={{ flex: `0 0 ${COL_ACTIVITY}px`, minWidth: 0, padding: "0 12px" }}>
                  {row.activity.length > 0 ? (
                    <span
                      style={{ fontSize: 12 }}
                      title={row.activity
                        .map((a) => `${a.standard_type} ${a.relation} ${a.value} ${a.unit} (${a.assay_key})`)
                        .join("; ")}
                    >
                      {row.activity.length === 1
                        ? activityText(row.activity[0])
                        : `${row.activity.length} measurements`}
                    </span>
                  ) : (
                    <span className="not-provided">none shown</span>
                  )}
                </div>
                <div style={{ flex: `0 0 ${COL_EVIDENCE}px`, padding: "0 12px" }}>
                  <button
                    className="evidence-link"
                    onClick={(e) => {
                      e.stopPropagation();
                      onSelectCompound(compound.id);
                    }}
                    aria-label={`Inspect evidence for compound ${compound.inchikey}`}
                  >
                    Source record
                  </button>
                </div>
              </div>
            );
          })}
        </div>
      </div>
      <div className="table-footer">
        <span>
          {page.total === 0
            ? "0 compounds"
            : `${page.offset + 1}–${page.offset + page.items.length} of ${page.total}`}
        </span>
        {selectedIds.size > 0 && (
          <span>
            {selectedIds.size} selected for save/export
            <button className="show-all-occ" style={{ marginLeft: 8 }} onClick={onClearSelection}>
              Clear selection
            </button>
          </span>
        )}
        <span className="fineprint">
          All identifiers and structures are illustrative (demo dataset).
        </span>
      </div>
    </div>
  );
}
