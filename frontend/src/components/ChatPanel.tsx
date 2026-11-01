import { useEffect, useRef, useState, type FormEvent, type KeyboardEvent } from "react";
import { askQuestionStream } from "../api/client";
import type { StoredMessage } from "../types";
import ChatMessage, { LiveMessage, type ChatEntry, type Citation, type LiveAnswer } from "./ChatMessage";
import EvidenceViewer from "./EvidenceViewer";

const MAX_QUESTION_LENGTH = 1000;

const EXAMPLE_QUESTIONS = [
  "What is this document about?",
  "Who are the parties?",
  "What are the termination conditions?",
];

// ChatEntry without its id (Omit distributed over each union member)
type NewEntry = ChatEntry extends infer E ? (E extends ChatEntry ? Omit<E, "id"> : never) : never;

interface ChatPanelProps {
  documentId: string;
  sessionId: string;
  initialMessages?: StoredMessage[]; // restored from a saved conversation
  onAnswered?: () => void;
}

// Saved messages -> the same entries live answers produce (no tool calls / timing)
function toEntries(stored: StoredMessage[]): ChatEntry[] {
  return stored.map((msg, id) =>
    msg.role === "user"
      ? { id, role: "user", text: msg.content }
      : {
          id,
          role: "assistant",
          answer: {
            answer: msg.content,
            found: msg.found,
            page_number: msg.page_number,
            reference_text: msg.reference_text,
          },
        },
  );
}

export default function ChatPanel({
  documentId,
  sessionId,
  initialMessages = [],
  onAnswered,
}: ChatPanelProps) {
  const [messages, setMessages] = useState<ChatEntry[]>(() => toEntries(initialMessages));
  const [input, setInput] = useState("");
  const [isWaiting, setIsWaiting] = useState(false);
  const [live, setLive] = useState<LiveAnswer | null>(null);
  const [evidence, setEvidence] = useState<Citation | null>(null);
  const listRef = useRef<HTMLDivElement>(null);
  const nextId = useRef(initialMessages.length);
  const abortRef = useRef<AbortController | null>(null);

  // Keep the newest message in view, also while an answer streams in
  useEffect(() => {
    const list = listRef.current;
    if (list) list.scrollTop = list.scrollHeight;
  }, [messages, live]);

  // Stop an in-flight stream on unmount (the panel is keyed by session)
  useEffect(() => () => abortRef.current?.abort(), []);

  function append(entry: NewEntry) {
    const withId = { ...entry, id: nextId.current++ } as ChatEntry;
    setMessages((prev) => [...prev, withId]);
  }

  async function send(text: string) {
    const question = text.trim();
    if (!question || isWaiting) return;

    append({ role: "user", text: question });
    setInput("");
    setIsWaiting(true);
    setLive({ steps: [], text: "" });
    const controller = new AbortController();
    abortRef.current = controller;
    try {
      await askQuestionStream(
        documentId,
        sessionId,
        question,
        {
          onTool: (name, args) =>
            setLive((prev) => prev && { ...prev, steps: [...prev.steps, { name, args }] }),
          onDelta: (text) => setLive((prev) => prev && { ...prev, text: prev.text + text }),
          // The final answer wins over the streamed text (the backend may replace it)
          onFinal: (answer) => {
            setLive(null);
            append({ role: "assistant", answer });
            onAnswered?.();
          },
          onError: (detail) => {
            setLive(null);
            append({ role: "error", text: `Error: ${detail}` });
          },
        },
        controller.signal,
      );
    } catch (err) {
      const message = err instanceof Error ? err.message : "Something went wrong.";
      append({ role: "error", text: `Error: ${message}` });
    } finally {
      if (abortRef.current === controller) abortRef.current = null;
      setLive(null);
      setIsWaiting(false);
    }
  }

  function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    void send(input);
  }

  // Enter sends, Shift+Enter inserts a newline
  function handleKeyDown(event: KeyboardEvent<HTMLTextAreaElement>) {
    if (event.key === "Enter" && !event.shiftKey && !event.nativeEvent.isComposing) {
      event.preventDefault();
      void send(input);
    }
  }

  return (
    <section className="card chat-panel">
      <div className="messages" ref={listRef}>
        {messages.length === 0 && !isWaiting ? (
          <div className="chat-empty">
            <p className="muted">Ask anything about this document.</p>
            <div className="quick-chips">
              {EXAMPLE_QUESTIONS.map((q) => (
                <button key={q} type="button" className="quick-chip" onClick={() => void send(q)}>
                  {q}
                </button>
              ))}
            </div>
          </div>
        ) : (
          messages.map((entry) => <ChatMessage key={entry.id} entry={entry} onShowEvidence={setEvidence} />)
        )}
        {live && <LiveMessage live={live} />}
      </div>

      <form className="chat-input" onSubmit={handleSubmit}>
        <span className="prompt-glyph" aria-hidden="true">&gt;</span>
        <textarea
          className="input-box"
          value={input}
          onChange={(e) => setInput(e.target.value)}
          onKeyDown={handleKeyDown}
          placeholder="Ask a question…"
          maxLength={MAX_QUESTION_LENGTH}
          rows={2}
          disabled={isWaiting}
          aria-label="Question"
        />
        <button type="submit" disabled={isWaiting || input.trim() === ""}>
          Ask
        </button>
      </form>

      {evidence && (
        <EvidenceViewer documentId={documentId} citation={evidence} onClose={() => setEvidence(null)} />
      )}
    </section>
  );
}
