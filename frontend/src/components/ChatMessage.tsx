import type { ChatAnswer, Source, ToolCallInfo } from "../types";

// Live answers carry tool calls and timing; answers restored from history do not
export type AssistantAnswer = Pick<ChatAnswer, "answer" | "page_number" | "reference_text" | "sources"> & {
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

export interface Citation {
  page: number;
  quote: string | null;
}

// Conversations saved before answers had several sources only have the single citation
function sourcesOf(answer: AssistantAnswer): Source[] {
  if (answer.found === false) return [];
  if (answer.sources.length > 0) return answer.sources;
  return answer.page_number === null
    ? []
    : [{ point: null, page_number: answer.page_number, reference_text: answer.reference_text ?? "" }];
}

function AssistantBody({ answer, onShowEvidence }: {
  answer: AssistantAnswer;
  onShowEvidence: (citation: Citation) => void;
}) {
  return (
    <>
      <p className="message-text">{answer.answer}</p>

      {sourcesOf(answer).map((source, i) => (
        <div className="message-source" key={i}>
          {source.point && <p className="source-point">{source.point}</p>}
          {source.reference_text && <p className="reference-line">“{source.reference_text}”</p>}
          <button
            type="button"
            className="evidence-button"
            onClick={() => onShowEvidence({ page: source.page_number, quote: source.reference_text })}
          >
            Show evidence · p. {source.page_number}
          </button>
        </div>
      ))}
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

export default function ChatMessage({ entry, onShowEvidence }: {
  entry: ChatEntry;
  onShowEvidence: (citation: Citation) => void;
}) {
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
      <AssistantBody answer={entry.answer} onShowEvidence={onShowEvidence} />
    </div>
  );
}

// Three bouncing dots shown while waiting for an answer
export function TypingIndicator() {
  return (
    <div className="typing-indicator" aria-label="Waiting for answer">
      <div className="dot" />
      <div className="dot" />
      <div className="dot" />
    </div>
  );
}

// Answer still streaming: the tools used so far plus the text received so far
export interface LiveAnswer {
  steps: ToolCallInfo[];
  text: string;
}

function argText(args: Record<string, unknown>, key: string): string {
  const value = args[key];
  return typeof value === "string" || typeof value === "number" ? String(value) : "";
}

// search_document({query: "notice"}) -> "Searching: notice"; unknown tools keep their name
function describeStep({ name, args }: ToolCallInfo): string {
  switch (name) {
    case "search_document":
      return `Searching: ${argText(args, "query")}`;
    case "get_page":
      return `Reading page ${argText(args, "page_number")}`;
    case "find_clauses":
      return `Finding clauses: ${argText(args, "category")}`;
    case "get_document_info":
      return "Reading document info";
    default:
      return name;
  }
}

export function LiveMessage({ live }: { live: LiveAnswer }) {
  const started = live.steps.length > 0 || live.text !== "";
  return (
    <div className="message bot" aria-busy="true">
      {!started && <TypingIndicator />}

      {live.steps.length > 0 && (
        <ol className="live-steps">
          {live.steps.map((step, i) => {
            // The latest step is in progress until answer text starts arriving
            const active = i === live.steps.length - 1 && live.text === "";
            return (
              <li key={i} className={active ? "live-step active" : "live-step"}>
                {active ? <span className="spinner" aria-hidden="true" /> : <span aria-hidden="true">✓</span>}
                <span>{describeStep(step)}</span>
              </li>
            );
          })}
        </ol>
      )}

      {live.text !== "" && (
        <p className="message-text">
          {live.text}
          <span className="stream-cursor" aria-hidden="true" />
        </p>
      )}
    </div>
  );
}
