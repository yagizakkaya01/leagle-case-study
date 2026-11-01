import type { ChatAnswer, ConversationDetail, ConversationSummary, DocumentInfo, PublicSettings } from "../types";
import { getClientId } from "./clientId";

const API_URL: string = import.meta.env.VITE_API_URL ?? "http://localhost:8000";

// Turns a non-2xx response into an Error carrying the backend's `detail` message.
async function toError(response: Response): Promise<Error> {
  try {
    const body: unknown = await response.json();
    if (body && typeof body === "object" && "detail" in body && typeof body.detail === "string") {
      return new Error(body.detail);
    }
  } catch {
    // Response body was not JSON; fall through to a generic message.
  }
  return new Error(`Request failed with status ${response.status}`);
}

// fetch with a friendly network error and `detail`-aware HTTP errors
async function request(path: string, init?: RequestInit): Promise<Response> {
  let response: Response;
  try {
    response = await fetch(`${API_URL}${path}`, init);
  } catch {
    throw new Error("Could not reach the server. Is the backend running?");
  }
  if (!response.ok) {
    throw await toError(response);
  }
  return response;
}

function clientQuery(): string {
  return `client_id=${encodeURIComponent(getClientId())}`;
}

export async function uploadDocument(file: File): Promise<DocumentInfo> {
  const form = new FormData();
  form.append("file", file);
  const response = await request("/api/documents", { method: "POST", body: form });
  return (await response.json()) as DocumentInfo;
}

export function documentFileUrl(documentId: string): string {
  return `${API_URL}/api/documents/${encodeURIComponent(documentId)}/file`;
}

export interface StreamHandlers {
  onTool: (name: string, args: Record<string, unknown>) => void;
  onDelta: (text: string) => void; // append to the answer shown so far
  onFinal: (answer: ChatAnswer) => void; // authoritative; may differ from the streamed text
  onError: (detail: string) => void;
}

interface SseFrame {
  event: string;
  data: string;
}

// "event: delta\ndata: {...}" -> {event, data}; repeated data lines are joined with "\n"
function parseFrame(raw: string): SseFrame | null {
  let event = "message";
  const data: string[] = [];
  for (const line of raw.split("\n")) {
    const colon = line.indexOf(":");
    if (colon <= 0) continue; // blank line or ":" comment (keep-alive)
    const field = line.slice(0, colon);
    const value = line.slice(colon + 1).replace(/^ /, "");
    if (field === "event") event = value;
    else if (field === "data") data.push(value);
  }
  return data.length > 0 ? { event, data: data.join("\n") } : null;
}

// Routes one frame to its handler; returns true once the stream is finished
function dispatch(frame: SseFrame, handlers: StreamHandlers): boolean {
  let payload: Record<string, unknown>;
  try {
    payload = JSON.parse(frame.data) as Record<string, unknown>;
  } catch {
    return false; // malformed frame: skip it
  }
  switch (frame.event) {
    case "tool":
      handlers.onTool(String(payload.name), (payload.args ?? {}) as Record<string, unknown>);
      return false;
    case "delta":
      handlers.onDelta(typeof payload.text === "string" ? payload.text : "");
      return false;
    case "final":
      handlers.onFinal(payload as unknown as ChatAnswer);
      return true;
    case "error":
      handlers.onError(typeof payload.detail === "string" ? payload.detail : "Something went wrong.");
      return true;
    default:
      return false;
  }
}

// Streams an answer over SSE (POST, so EventSource is not an option).
// Validation and network errors are thrown; errors during the stream go to onError.
// An aborted stream returns silently.
export async function askQuestionStream(
  documentId: string,
  sessionId: string,
  question: string,
  handlers: StreamHandlers,
  signal?: AbortSignal,
): Promise<void> {
  let response: Response;
  try {
    response = await request("/api/chat/stream", {
      method: "POST",
      headers: { "Content-Type": "application/json", Accept: "text/event-stream" },
      body: JSON.stringify({
        document_id: documentId,
        session_id: sessionId,
        client_id: getClientId(),
        question,
      }),
      signal,
    });
  } catch (err) {
    if (signal?.aborted) return;
    throw err;
  }
  if (!response.body) {
    handlers.onError("The connection was interrupted.");
    return;
  }

  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  try {
    for (;;) {
      const { done, value } = await reader.read();
      // Drop CR so both LF and CRLF line endings split the same way
      buffer += decoder.decode(value, { stream: !done }).replace(/\r/g, "");

      let boundary = buffer.indexOf("\n\n");
      while (boundary !== -1) {
        const frame = parseFrame(buffer.slice(0, boundary));
        buffer = buffer.slice(boundary + 2);
        if (frame && dispatch(frame, handlers)) {
          await reader.cancel();
          return;
        }
        boundary = buffer.indexOf("\n\n");
      }

      if (done) break;
    }
    // A last frame without the trailing blank line
    const frame = parseFrame(buffer);
    if (frame && dispatch(frame, handlers)) return;
  } catch {
    if (signal?.aborted) return;
  }
  handlers.onError("The connection was interrupted.");
}

export async function getPublicSettings(): Promise<PublicSettings> {
  const response = await request("/api/settings");
  return (await response.json()) as PublicSettings;
}

export async function listConversations(): Promise<ConversationSummary[]> {
  const response = await request(`/api/conversations?${clientQuery()}`);
  return (await response.json()) as ConversationSummary[];
}

export async function getConversation(sessionId: string): Promise<ConversationDetail> {
  const id = encodeURIComponent(sessionId);
  const response = await request(`/api/conversations/${id}?${clientQuery()}`);
  return (await response.json()) as ConversationDetail;
}

export async function deleteConversation(sessionId: string): Promise<void> {
  const id = encodeURIComponent(sessionId);
  await request(`/api/conversations/${id}?${clientQuery()}`, { method: "DELETE" });
}
