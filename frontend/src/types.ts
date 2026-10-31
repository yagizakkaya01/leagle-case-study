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

export interface DocumentInfo {
  document_id: string; // sha256 of the file
  filename: string;
  page_count: number;
  chunk_count: number;
  empty_pages: number[]; // 1-based pages with no extractable text
  metadata: DocumentMetadata;
}
