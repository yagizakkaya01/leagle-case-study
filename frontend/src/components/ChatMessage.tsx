import type { ChatAnswer, ToolCallInfo } from "../types";

// Live answers carry tool calls and timing; answers restored from history do not
export type AssistantAnswer = Pick<ChatAnswer, "answer" | "page_number" | "reference_text"> & {
  found: boolean | null;
  tool_calls?: ToolCallInfo[];
  elapsed_seconds?: number;
};

export type ChatEntry =
  | { id: number; role: "user"; text: string }
  | { id: number; role: "assistant"; answer: AssistantAnswer }
  | { id: number; role: "error"; text: string };

// {"query": "termination", "page": 3} -> 'search(query="termination", page=3)'
function formatToolCall(call: ToolCallInfo): string {
  const args = Object.entries(call.args)
    .map(([key, value]) => `${key}=${JSON.stringify(value)}`)
    .join(", ");
  return `${call.name}(${args})`;
}

function AssistantBody({ answer }: { answer: AssistantAnswer }) {
  return (
    <>
      <p className="message-text">{answer.answer}</p>

      {answer.found !== false && answer.page_number !== null && (
        <div className="message-source">
          <span className="source-tag">📄 p. {answer.page_number}</span>
          {answer.reference_text && (
            <blockquote className="reference-quote">{answer.reference_text}</blockquote>
          )}
        </div>
      )}
      {answer.found === false && <p className="callout callout-muted small">No reference in the document</p>}

      {answer.elapsed_seconds !== undefined && (
        <span className="meta-info">⏱ {answer.elapsed_seconds.toFixed(2)}s</span>
      )}

      {answer.tool_calls && answer.tool_calls.length > 0 && (
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
