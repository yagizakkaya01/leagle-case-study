import type { ChatAnswer, ToolCallInfo } from "../types";

export type ChatEntry =
  | { id: number; role: "user"; text: string }
  | { id: number; role: "assistant"; answer: ChatAnswer }
  | { id: number; role: "error"; text: string };

// {"query": "termination", "page": 3} -> 'search(query="termination", page=3)'
function formatToolCall(call: ToolCallInfo): string {
  const args = Object.entries(call.args)
    .map(([key, value]) => `${key}=${JSON.stringify(value)}`)
    .join(", ");
  return `${call.name}(${args})`;
}

function AssistantBody({ answer }: { answer: ChatAnswer }) {
  return (
    <>
      <p className="message-text">{answer.answer}</p>

      {answer.found && answer.page_number !== null && (
        <div className="message-source">
          <span className="source-tag">📄 p. {answer.page_number}</span>
          {answer.reference_text && (
            <blockquote className="reference-quote">{answer.reference_text}</blockquote>
          )}
        </div>
      )}
      {!answer.found && <p className="callout callout-muted small">Not found in the document</p>}

      <span className="meta-info">⏱ {answer.elapsed_seconds.toFixed(2)}s</span>

      {answer.tool_calls.length > 0 && (
        <details className="tool-calls">
          <summary>How this answer was found</summary>
          <ol>
            {answer.tool_calls.map((call, i) => (
              <li key={i}>
                <code>{formatToolCall(call)}</code>
              </li>
            ))}
          </ol>
        </details>
      )}
    </>
  );
}

export default function ChatMessage({ entry }: { entry: ChatEntry }) {
  if (entry.role === "user") {
    return <div className="message user">{entry.text}</div>;
  }
  if (entry.role === "error") {
    return (
      <div className="message bot message-error" role="alert">
        {entry.text}
      </div>
    );
  }
  return (
    <div className="message bot">
      <AssistantBody answer={entry.answer} />
    </div>
  );
}

// Three bouncing dots shown while waiting for an answer
export function TypingIndicator() {
  return (
    <div className="message bot" aria-label="Waiting for answer">
      <div className="typing-indicator">
        <div className="dot" />
        <div className="dot" />
        <div className="dot" />
      </div>
    </div>
  );
}
