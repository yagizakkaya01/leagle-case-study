export interface DocumentInfo {
  document_id: string; // sha256 of the file
  filename: string;
  page_count: number;
  chunk_count: number;
  empty_pages: number[]; // 1-based pages with no extractable text
}
