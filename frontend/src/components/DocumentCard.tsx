import type { ReactNode } from "react";
import type { DocumentInfo } from "../types";

interface DocumentCardProps {
  doc: DocumentInfo;
  onReset: () => void;
  onNewChat: () => void;
}

// "court_decision" -> "Court decision"
function humanize(key: string): string {
  const text = key.replace(/_/g, " ").trim();
  return text.charAt(0).toUpperCase() + text.slice(1);
}

function Section({ label, children }: { label: string; children: ReactNode }) {
  return (
    <div className="doc-section">
      <h3 className="section-label">{label}</h3>
      {children}
    </div>
  );
}

export default function DocumentCard({ doc, onReset, onNewChat }: DocumentCardProps) {
  const meta = doc.metadata;
  const clauses = Object.entries(meta.clause_categories).filter(([, count]) => count > 0);

  return (
    <section className="card document-card">
      <div className="doc-header">
        <h2>{meta.title ?? doc.filename}</h2>
        <div className="badges">
          <span className="badge badge-type">{humanize(meta.document_type)}</span>
          {meta.language && <span className="badge">{meta.language.toUpperCase()}</span>}
          <span className="muted doc-stats">
            {doc.page_count} pages · {doc.chunk_count} chunks
          </span>
        </div>
        {meta.title && meta.title !== doc.filename && <p className="muted small">{doc.filename}</p>}
      </div>

      <p className="callout callout-success">
        <span className="status-label">Indexed</span>
        Ready for questions
      </p>

      {meta.summary && <p className="doc-summary">{meta.summary}</p>}
      {!meta.llm_enriched && (
        <p className="muted small llm-note">Summary and parties unavailable (the language model was not reachable)</p>
      )}

      {meta.parties.length > 0 && (
        <Section label="Parties">
          <ul className="doc-list">
            {meta.parties.map((party, i) => (
              <li key={i}>
                {party.name}
                {party.role && <span className="muted"> — {party.role}</span>}
              </li>
            ))}
          </ul>
        </Section>
      )}

      {meta.key_dates.length > 0 && (
        <Section label="Key dates">
          <ul className="doc-list">
            {meta.key_dates.map((item, i) => (
              <li key={i}>
                {item.label}: {item.date}
                {item.page !== null && <span className="muted"> (p. {item.page})</span>}
              </li>
            ))}
          </ul>
        </Section>
      )}

      {meta.governing_law && (
        <Section label="Governing law">
          <p>{meta.governing_law}</p>
        </Section>
      )}

      {meta.case_numbers.length > 0 && (
        <Section label="Case numbers">
          <div className="tags">
            {meta.case_numbers.map((num) => (
              <span key={num} className="source-tag">{num}</span>
            ))}
          </div>
        </Section>
      )}

      {clauses.length > 0 && (
        <Section label="Clause categories">
          <div className="tags">
            {clauses.map(([key, count]) => (
              <span key={key} className="chip">
                {humanize(key)} <span className="chip-count">{count}</span>
              </span>
            ))}
          </div>
        </Section>
      )}

      {meta.outline.length > 0 && (
        <details className="doc-outline">
          <summary>Outline ({meta.outline.length})</summary>
          <ul className="doc-list">
            {meta.outline.map((item, i) => (
              <li key={i}>
                {item.heading} <span className="muted">— p. {item.page}</span>
              </li>
            ))}
          </ul>
        </details>
      )}

      {doc.empty_pages.length > 0 && (
        <p className="callout warning">No extractable text on pages: {doc.empty_pages.join(", ")}</p>
      )}

      <div className="doc-actions">
        <button type="button" className="btn-secondary" onClick={onNewChat}>
          New chat on this document
        </button>
        <button type="button" className="btn-secondary" onClick={onReset}>
          Upload another PDF
        </button>
      </div>
    </section>
  );
}
