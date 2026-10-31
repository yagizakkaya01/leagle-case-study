import { useState } from "react";
import UploadPanel from "./components/UploadPanel";
import type { DocumentInfo } from "./types";

export default function App() {
  const [doc, setDoc] = useState<DocumentInfo | null>(null);

  return (
    <div className="app">
      <header className="app-header">
        <h1>Legal Document Chat</h1>
      </header>

      <main>
        {doc === null ? (
          <UploadPanel onUploaded={setDoc} />
        ) : (
          <>
            <section className="card document-summary">
              <h2>{doc.filename}</h2>
              <p>
                {doc.page_count} pages · {doc.chunk_count} chunks
              </p>
              {doc.empty_pages.length > 0 && (
                <p className="warning">
                  No extractable text on pages: {doc.empty_pages.join(", ")}
                </p>
              )}
              <button type="button" onClick={() => setDoc(null)}>
                Upload another PDF
              </button>
            </section>

            {/* Placeholder: chat UI arrives next iteration */}
            <section className="chat-placeholder">Chat coming next</section>
          </>
        )}
      </main>
    </div>
  );
}
