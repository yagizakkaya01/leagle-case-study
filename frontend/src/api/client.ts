import type { ChatAnswer, DocumentInfo } from "../types";

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

export async function uploadDocument(file: File): Promise<DocumentInfo> {
  const form = new FormData();
  form.append("file", file);

  let response: Response;
  try {
    response = await fetch(`${API_URL}/api/documents`, { method: "POST", body: form });
  } catch {
    throw new Error("Could not reach the server. Is the backend running?");
  }

  if (!response.ok) {
    throw await toError(response);
  }
  return (await response.json()) as DocumentInfo;
}

export async function askQuestion(
  documentId: string,
  sessionId: string,
  question: string,
): Promise<ChatAnswer> {
  let response: Response;
  try {
    response = await fetch(`${API_URL}/api/chat`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ document_id: documentId, session_id: sessionId, question }),
    });
  } catch {
    throw new Error("Could not reach the server. Is the backend running?");
  }

  if (!response.ok) {
    throw await toError(response);
  }
  return (await response.json()) as ChatAnswer;
}
