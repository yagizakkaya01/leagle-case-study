import { useState, type ChangeEvent, type FormEvent } from "react";
import { uploadDocument } from "../api/client";
import type { DocumentInfo } from "../types";

const MAX_FILE_SIZE_MB = 10;
const MAX_FILE_SIZE_BYTES = MAX_FILE_SIZE_MB * 1024 * 1024;

interface UploadPanelProps {
  onUploaded: (doc: DocumentInfo) => void;
}

function validateFile(file: File): string | null {
  const isPdf = file.type === "application/pdf" || file.name.toLowerCase().endsWith(".pdf");
  if (!isPdf) return "Please choose a PDF file.";
  if (file.size > MAX_FILE_SIZE_BYTES) return `File is too large (max ${MAX_FILE_SIZE_MB} MB).`;
  return null;
}

export default function UploadPanel({ onUploaded }: UploadPanelProps) {
  const [file, setFile] = useState<File | null>(null);
  const [isUploading, setIsUploading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  function handleFileChange(event: ChangeEvent<HTMLInputElement>) {
    const selected = event.target.files?.[0] ?? null;
    setFile(selected);
    setError(selected ? validateFile(selected) : null);
  }

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!file) return;

    const validationError = validateFile(file);
    if (validationError) {
      setError(validationError);
      return;
    }

    setIsUploading(true);
    setError(null);
    try {
      onUploaded(await uploadDocument(file));
    } catch (err) {
      setError(err instanceof Error ? err.message : "Upload failed.");
    } finally {
      setIsUploading(false);
    }
  }

  const canUpload = file !== null && error === null && !isUploading;

  return (
    <form className="card upload-panel" onSubmit={handleSubmit}>
      <span className="eyebrow">01 · Upload</span>
      <h2>Upload a PDF</h2>
      <p className="muted">Choose a single PDF (max {MAX_FILE_SIZE_MB} MB) to start chatting with it.</p>

      <input
        type="file"
        accept=".pdf,application/pdf"
        onChange={handleFileChange}
        disabled={isUploading}
      />

      <button type="submit" disabled={!canUpload}>
        {isUploading ? "Processing…" : "Upload"}
      </button>

      {error && <p className="error" role="alert">{error}</p>}
    </form>
  );
}
