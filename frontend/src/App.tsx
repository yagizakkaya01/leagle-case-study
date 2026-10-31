import { useRef, useState } from "react";
import { getConversation } from "./api/client";
import ChatPanel from "./components/ChatPanel";
import ConversationSidebar from "./components/ConversationSidebar";
import DemoBanner from "./components/DemoBanner";
import DocumentCard from "./components/DocumentCard";
import UploadPanel from "./components/UploadPanel";
import type { DocumentInfo, StoredMessage } from "./types";

export default function App() {
  const [doc, setDoc] = useState<DocumentInfo | null>(null);
  const [sessionId, setSessionId] = useState<string | null>(null);
  const [initialMessages, setInitialMessages] = useState<StoredMessage[]>([]);
  const [refreshKey, setRefreshKey] = useState(0);
  const [sidebarOpen, setSidebarOpen] = useState(false);
  const [openError, setOpenError] = useState<string | null>(null);
  const [isOpening, setIsOpening] = useState(false);
  // Ignores a slow detail response once the user has clicked something else
  const openRequest = useRef(0);

  function startSession(nextDoc: DocumentInfo | null, nextSession: string | null) {
    openRequest.current++;
    setDoc(nextDoc);
    setSessionId(nextSession);
    setInitialMessages([]);
    setOpenError(null);
    setIsOpening(false);
  }

  // Each uploaded document starts a fresh chat session
  function handleUploaded(uploaded: DocumentInfo) {
    startSession(uploaded, crypto.randomUUID());
  }

  function handleReset() {
    startSession(null, null);
    setSidebarOpen(false);
  }

  function handleNewChat() {
    if (doc) startSession(doc, crypto.randomUUID());
  }

  async function handleSelect(id: string) {
    setSidebarOpen(false);
    if (id === sessionId) return;
    const request = ++openRequest.current;
    setIsOpening(true);
    setOpenError(null);
    try {
      const detail = await getConversation(id);
      if (request !== openRequest.current) return;
      setDoc(detail.document);
      setSessionId(detail.session_id);
      setInitialMessages(detail.messages);
    } catch (err) {
      if (request !== openRequest.current) return;
      setOpenError(err instanceof Error ? err.message : "Could not open the conversation.");
    } finally {
      if (request === openRequest.current) setIsOpening(false);
    }
  }

  function handleDeleted(id: string) {
    if (id === sessionId) startSession(null, null);
    setRefreshKey((k) => k + 1);
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
          <button
            type="button"
            className="sidebar-toggle"
            onClick={() => setSidebarOpen((open) => !open)}
            aria-expanded={sidebarOpen}
            aria-controls="conversation-sidebar"
          >
            Conversations
          </button>
        </div>
      </header>
      <DemoBanner />

      <div className="app-body">
        <ConversationSidebar
          activeSessionId={sessionId}
          refreshKey={refreshKey}
          isOpen={sidebarOpen}
          onSelect={(id) => void handleSelect(id)}
          onNewDocument={handleReset}
          onDeleted={handleDeleted}
        />

        <main className="app-main">
          {openError && (
            <p className="callout warning" role="alert">
              {openError}
            </p>
          )}
          {isOpening && <p className="muted small">Opening conversation…</p>}

          {doc === null || sessionId === null ? (
            <UploadPanel onUploaded={handleUploaded} />
          ) : (
            <>
              <DocumentCard doc={doc} onReset={handleReset} onNewChat={handleNewChat} />
              {/* Keyed by session so switching conversations starts from its own messages */}
              <ChatPanel
                key={sessionId}
                documentId={doc.document_id}
                sessionId={sessionId}
                initialMessages={initialMessages}
                onAnswered={() => setRefreshKey((k) => k + 1)}
              />
            </>
          )}
        </main>
      </div>
    </div>
  );
}
