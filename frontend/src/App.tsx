import { useState } from "react";
import ChatPanel from "./components/ChatPanel";
import DocumentCard from "./components/DocumentCard";
import UploadPanel from "./components/UploadPanel";
import type { DocumentInfo } from "./types";

export default function App() {
  const [doc, setDoc] = useState<DocumentInfo | null>(null);
  const [sessionId, setSessionId] = useState<string | null>(null);

  // Each uploaded document starts a fresh chat session
  function handleUploaded(uploaded: DocumentInfo) {
    setDoc(uploaded);
    setSessionId(crypto.randomUUID());
  }

  function handleReset() {
    setDoc(null);
    setSessionId(null);
  }

  return (
    <div className="app">
      <header className="app-header">
        <div className="hero-inner">
          <div className="brand">
            <span className="brand-name">Legal Document Chat</span>
            <span className="brand-sub">Ask questions about your PDF</span>
          </div>
          <h1 className="hero-title">Ask your document. Get the page and the quote.</h1>
        </div>
      </header>

      <main className="app-main">
        {doc === null || sessionId === null ? (
          <UploadPanel onUploaded={handleUploaded} />
        ) : (
          <>
            <DocumentCard doc={doc} onReset={handleReset} />
            {/* Keyed by session so a new upload starts with an empty message list */}
            <ChatPanel key={sessionId} documentId={doc.document_id} sessionId={sessionId} />
          </>
        )}
      </main>
    </div>
  );
}
