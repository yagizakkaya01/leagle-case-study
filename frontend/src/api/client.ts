import type {
  ChatAnswer,
  ConversationDetail,
  ConversationSummary,
  DocumentInfo,
} from "../types";
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

export async function askQuestion(
  documentId: string,
  sessionId: string,
  question: string,
): Promise<ChatAnswer> {
  const response = await request("/api/chat", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      document_id: documentId,
      session_id: sessionId,
      client_id: getClientId(),
      question,
    }),
  });
  return (await response.json()) as ChatAnswer;
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
