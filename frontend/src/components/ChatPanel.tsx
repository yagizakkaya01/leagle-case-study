import { useEffect, useRef, useState, type FormEvent, type KeyboardEvent } from "react";
import { askQuestion } from "../api/client";
import ChatMessage, { TypingIndicator, type ChatEntry } from "./ChatMessage";

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
}

export default function ChatPanel({ documentId, sessionId }: ChatPanelProps) {
  const [messages, setMessages] = useState<ChatEntry[]>([]);
  const [input, setInput] = useState("");
  const [isWaiting, setIsWaiting] = useState(false);
  const listRef = useRef<HTMLDivElement>(null);
  const nextId = useRef(0);

  // Keep the newest message in view
  useEffect(() => {
    const list = listRef.current;
    if (list) list.scrollTop = list.scrollHeight;
  }, [messages, isWaiting]);

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
    try {
      const answer = await askQuestion(documentId, sessionId, question);
      append({ role: "assistant", answer });
    } catch (err) {
      const message = err instanceof Error ? err.message : "Something went wrong.";
      append({ role: "error", text: `Error: ${message}` });
    } finally {
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
          messages.map((entry) => <ChatMessage key={entry.id} entry={entry} />)
        )}
        {isWaiting && <TypingIndicator />}
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
    </section>
  );
}
