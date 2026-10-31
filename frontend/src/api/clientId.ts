const STORAGE_KEY = "ldc.client_id";

// Fallback when localStorage is unavailable (private mode, blocked storage)
let memoryId: string | null = null;

// Anonymous per-browser id that scopes saved conversations
export function getClientId(): string {
  try {
    const stored = localStorage.getItem(STORAGE_KEY);
    if (stored) return stored;
    const created = crypto.randomUUID();
    localStorage.setItem(STORAGE_KEY, created);
    return created;
  } catch {
    memoryId ??= crypto.randomUUID();
    return memoryId;
  }
}
