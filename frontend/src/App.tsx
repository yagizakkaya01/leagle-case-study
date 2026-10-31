import { useState } from "react";
import DocumentCard from "./components/DocumentCard";
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
            <DocumentCard doc={doc} onReset={() => setDoc(null)} />

            {/* Placeholder: chat UI arrives next iteration */}
            <section className="chat-placeholder">Chat coming next</section>
          </>
        )}
      </main>
    </div>
  );
}
