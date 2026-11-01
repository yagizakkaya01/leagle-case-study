export type DocumentType =
  | "contract"
  | "court_decision"
  | "legislation"
  | "regulation"
  | "pleading"
  | "legal_opinion"
  | "policy"
  | "correspondence"
  | "other";

export interface Party {
  name: string;
  role: string | null;
}

export interface KeyDate {
  label: string;
  date: string; // ISO yyyy-mm-dd, or free text if unparseable
  page: number | null;
}

export interface OutlineItem {
  heading: string;
  page: number;
}

export interface DocumentMetadata {
  document_type: DocumentType;
  title: string | null;
  language: string | null; // e.g. "en", "tr"
  summary: string | null;
  parties: Party[];
  key_dates: KeyDate[];
  governing_law: string | null;
  case_numbers: string[]; // e.g. "2022/123 E.", "2024/55 K."
  outline: OutlineItem[];
  clause_categories: Record<string, number>; // e.g. {"termination": 2, "payment": 3}
  llm_enriched: boolean; // false when no LLM key: only rule-based fields filled
}

export interface PublicSettings {
  demo_notice: string | null;
  retention_hours: number | null;
}

export interface DocumentInfo {
  document_id: string; // sha256 of the file
  filename: string;
  page_count: number;
  chunk_count: number;
  empty_pages: number[]; // 1-based pages with no extractable text
  metadata: DocumentMetadata;
}

export interface ToolCallInfo {
  name: string;
  args: Record<string, unknown>;
}

// A verified citation; `point` names what it supports when an answer has several
export interface Source {
  point: string | null;
  page_number: number;
  reference_text: string;
}

export interface ChatAnswer {
  answer: string;
  page_number: number | null; // 1-based, verified by backend
  reference_text: string | null; // short quote from the document, verified
  found: boolean; // false when the document does not contain the answer
  sources: Source[]; // one per point; the first matches page_number/reference_text
  tool_calls: ToolCallInfo[]; // tools the model used, in order
  elapsed_seconds: number;
}

// Saved conversation as listed in the sidebar (newest first)
export interface ConversationSummary {
  session_id: string;
  document_id: string;
  filename: string;
  title: string;
  updated_at: string; // ISO timestamp
}

export interface StoredMessage {
  role: "user" | "assistant";
  content: string;
  found: boolean | null;
  page_number: number | null;
  reference_text: string | null;
  sources: Source[];
}

export interface ConversationDetail {
  session_id: string;
  document: DocumentInfo;
  messages: StoredMessage[];
}

export interface HighlightBox {
  x: number;
  top: number;
  width: number;
  height: number;
}
