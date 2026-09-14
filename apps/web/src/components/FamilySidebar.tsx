import type { PatentResponse } from "../api/types";

interface FamilySidebarProps {
  patent: PatentResponse | null;
  selectedDocId: string | null;
  collapsed: boolean;
  onSelectDoc: (docId: string | null) => void;
}

/** Left column: current family and its member documents.
 * Selecting a document narrows the table scope; "All documents" is family-wide. */
export function FamilySidebar({ patent, selectedDocId, collapsed, onSelectDoc }: FamilySidebarProps) {
  if (collapsed || !patent) return null;
  const totalMentions = Object.values(patent.mention_counts).reduce((a, b) => a + b, 0);

  return (
    <nav className="sidebar" aria-label="Patent family">
      <h2>Patent family</h2>
      <div className="family-title">{patent.family.title ?? patent.family.family_key}</div>
      <div className="family-meta">
        {patent.documents.length} document{patent.documents.length === 1 ? "" : "s"} ·{" "}
        {totalMentions} structure record{totalMentions === 1 ? "" : "s"}
      </div>

      <button
        className="scope-option"
        aria-current={selectedDocId === null}
        onClick={() => onSelectDoc(null)}
      >
        All documents
        <span className="count">deduped</span>
      </button>

      {patent.documents.map((doc) => (
        <button
          key={doc.id}
          className="scope-option"
          aria-current={selectedDocId === doc.id}
          onClick={() => onSelectDoc(doc.id)}
          title={doc.title ?? doc.publication_number}
        >
          <span>
            <span className="mono">{doc.publication_number}</span>
            <br />
            <span className="doc-jur">
              {doc.jurisdiction ?? "?"} · {doc.doc_type ?? "document"}
            </span>
          </span>
          <span className="count">{patent.mention_counts[doc.id] ?? 0}</span>
        </button>
      ))}
    </nav>
  );
}
