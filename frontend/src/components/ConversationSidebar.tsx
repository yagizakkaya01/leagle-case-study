import { useEffect, useState } from "react";
import { deleteConversation, listConversations } from "../api/client";
import type { ConversationSummary } from "../types";

interface ConversationSidebarProps {
  activeSessionId: string | null;
  refreshKey: number; // bump to re-fetch the list
  isOpen: boolean; // only matters below 900px, where the sidebar collapses
  onSelect: (sessionId: string) => void;
  onNewDocument: () => void;
  onDeleted: (sessionId: string) => void;
}

// ISO timestamp -> "just now", "5 min ago", "3 h ago", "2 days ago", or a date
function relativeTime(iso: string): string {
  const time = new Date(iso).getTime();
  if (Number.isNaN(time)) return "";
  const minutes = Math.floor((Date.now() - time) / 60_000);
  if (minutes < 1) return "just now";
  if (minutes < 60) return `${minutes} min ago`;
  const hours = Math.floor(minutes / 60);
  if (hours < 24) return `${hours} h ago`;
  const days = Math.floor(hours / 24);
  if (days < 7) return days === 1 ? "1 day ago" : `${days} days ago`;
  return new Date(time).toLocaleDateString();
}

function errorText(err: unknown, fallback: string): string {
  return err instanceof Error ? err.message : fallback;
}

export default function ConversationSidebar({
  activeSessionId,
  refreshKey,
  isOpen,
  onSelect,
  onNewDocument,
  onDeleted,
}: ConversationSidebarProps) {
  const [items, setItems] = useState<ConversationSummary[] | null>(null); // null = first load
  const [error, setError] = useState<string | null>(null);
  const [retryTick, setRetryTick] = useState(0);

  useEffect(() => {
    let cancelled = false;
    listConversations()
      .then((list) => {
        if (cancelled) return;
        setItems(list);
        setError(null);
      })
      .catch((err: unknown) => {
        if (!cancelled) setError(errorText(err, "Could not load conversations."));
      });
    return () => {
      cancelled = true;
    };
  }, [refreshKey, retryTick]);

  // Remove right away; put the list back if the server refuses
  async function handleDelete(sessionId: string) {
    const previous = items;
    setItems((list) => list?.filter((c) => c.session_id !== sessionId) ?? null);
    try {
      await deleteConversation(sessionId);
      onDeleted(sessionId);
    } catch (err) {
      setItems(previous);
      setError(errorText(err, "Could not delete the conversation."));
    }
  }

  return (
    <aside
      id="conversation-sidebar"
      className={`card sidebar${isOpen ? " open" : ""}`}
      aria-label="Saved conversations"
    >
      <button type="button" className="new-doc-btn" onClick={onNewDocument}>
        + New document
      </button>

      <h2 className="section-label">Conversations</h2>

      {error && (
        <div className="history-state history-error" role="alert">
          <span>{error}</span>
          <button type="button" className="link-btn" onClick={() => setRetryTick((t) => t + 1)}>
            Retry
          </button>
        </div>
      )}

      {items === null && !error && <p className="history-state">Loading…</p>}
      {items !== null && items.length === 0 && (
        <p className="history-state">No conversations yet</p>
      )}

      {items !== null && items.length > 0 && (
        <ul className="history-list">
          {items.map((c) => (
            <li
              key={c.session_id}
              className={`history-item${c.session_id === activeSessionId ? " active" : ""}`}
            >
              <button
                type="button"
                className="history-open"
                onClick={() => onSelect(c.session_id)}
                aria-current={c.session_id === activeSessionId ? "true" : undefined}
              >
                <span className="history-title">{c.title}</span>
                <span className="history-meta">
                  <span className="history-file">{c.filename}</span>
                  <span>· {relativeTime(c.updated_at)}</span>
                </span>
              </button>
              <button
                type="button"
                className="history-delete"
                onClick={() => void handleDelete(c.session_id)}
                aria-label={`Delete conversation "${c.title}"`}
                title="Delete"
              >
                ×
              </button>
            </li>
          ))}
        </ul>
      )}
    </aside>
  );
}
