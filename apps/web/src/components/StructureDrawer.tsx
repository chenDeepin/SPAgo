import { useState } from "react";
import type { Compound } from "../api/types";
import { Modal } from "./Modal";

interface StructureDrawerProps {
  compound: Compound;
  labels: string[];
  onClose: () => void;
}

function CopyRow({ label, value }: { label: string; value: string }) {
  const [copied, setCopied] = useState(false);
  return (
    <div className="identity-row">
      <span style={{ color: "var(--text-2)" }}>{label}:</span>
      <span className="mono"> {value}</span>
      <button
        className="copy-btn"
        onClick={async () => {
          try {
            await navigator.clipboard.writeText(value);
            setCopied(true);
            setTimeout(() => setCopied(false), 1500);
          } catch {
            setCopied(false);
          }
        }}
      >
        {copied ? "Copied" : "Copy"}
      </button>
    </div>
  );
}

/** Larger structure preview (design doc: complex molecules may open a bigger
 * preview, never truncated). Identity supports copy; no editing here. */
export function StructureDrawer({ compound, labels, onClose }: StructureDrawerProps) {
  return (
    <Modal title="Structure" onClose={onClose} wide>
      <div className="structure-drawer-body">
        <img
          className="depiction structure-large"
          src={`/api/v1/compounds/${compound.id}/depiction?w=560&h=320`}
          alt="2D structure depiction, large preview"
        />
        <div>
          <div className="evidence-compound">
            {labels.length > 0 ? `${labels.join(", ")} — ` : ""}
            <span className="mono">{compound.inchikey}</span>
          </div>
          <CopyRow label="Canonical SMILES" value={compound.canonical_smiles} />
          <CopyRow label="InChIKey" value={compound.inchikey} />
          {compound.inchi && <CopyRow label="InChI" value={compound.inchi} />}
          <div className="identity-row">
            <span style={{ color: "var(--text-2)" }}>Formula:</span> {compound.molecular_formula ?? "—"}
            {compound.molecular_weight != null && ` · ${compound.molecular_weight} Da`}
          </div>
          <div className="identity-row">
            <span style={{ color: "var(--text-2)" }}>Stereo:</span>{" "}
            {compound.has_stereo
              ? "specified in source; preserved"
              : "not specified in source structure"}
          </div>
          {compound.is_multi_component && (
            <div className="identity-row">
              <span style={{ color: "var(--text-2)" }}>Components:</span> multi-component record;
              salt/parent handling is a later milestone.
            </div>
          )}
        </div>
      </div>
    </Modal>
  );
}
