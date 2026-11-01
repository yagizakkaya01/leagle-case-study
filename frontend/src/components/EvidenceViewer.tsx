import { useEffect, useRef, useState } from "react";
import type { PDFDocumentProxy } from "pdfjs-dist";
import workerUrl from "pdfjs-dist/build/pdf.worker.min.mjs?url";
import { documentFileUrl } from "../api/client";
import type { Citation } from "./ChatMessage";
import { locateQuote, type Box, type TextRun } from "./locateQuote";

const MAX_RENDER_SCALE = 3;
const ZOOM_FACTOR = 2; // the page is rendered for this width, so zooming in stays sharp

// pdf.js is large, so it is loaded the first time someone opens a citation
async function loadPdfjs() {
  const pdfjs = await import("pdfjs-dist");
  pdfjs.GlobalWorkerOptions.workerSrc = workerUrl;
  return pdfjs;
}

interface PageView {
  boxes: Box[]; // in percent of the page, so they follow the canvas size
}

interface EvidenceViewerProps {
  documentId: string;
  citation: Citation;
  onClose: () => void;
}

export default function EvidenceViewer({ documentId, citation, onClose }: EvidenceViewerProps) {
  const dialogRef = useRef<HTMLDialogElement>(null);
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const firstBoxRef = useRef<HTMLDivElement>(null);
  const [pdf, setPdf] = useState<PDFDocumentProxy | null>(null);
  const [pageNumber, setPageNumber] = useState(citation.page);
  const [view, setView] = useState<PageView | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [zoomed, setZoomed] = useState(false);

  // A native modal dialog brings the backdrop, focus trap and Esc to close
  useEffect(() => {
    const dialog = dialogRef.current;
    if (dialog && !dialog.open) dialog.showModal();
  }, []);

  useEffect(() => {
    let destroy: (() => void) | undefined;
    let cancelled = false;
    void (async () => {
      try {
        const pdfjs = await loadPdfjs();
        if (cancelled) return;
        const task = pdfjs.getDocument({ url: documentFileUrl(documentId) });
        destroy = () => void task.destroy();
        const loaded = await task.promise;
        if (!cancelled) setPdf(loaded);
      } catch {
        if (!cancelled) setError("The original file could not be opened. It may have expired.");
      }
    })();
    return () => {
      cancelled = true;
      destroy?.();
    };
  }, [documentId]);

  useEffect(() => {
    const canvas = canvasRef.current;
    if (!pdf || !canvas) return;
    let cancelled = false;
    let cancelRender: (() => void) | undefined;
    setView(null);
    void (async () => {
      try {
        const pdfjs = await loadPdfjs();
        const page = await pdf.getPage(pageNumber);
        if (cancelled) return;
        const base = page.getViewport({ scale: 1 });
        const fitWidth = canvas.closest(".evidence-scroll")!.clientWidth;
        const wanted = (fitWidth * ZOOM_FACTOR * window.devicePixelRatio) / base.width;
        const viewport = page.getViewport({ scale: Math.min(wanted, MAX_RENDER_SCALE) });
        canvas.width = Math.floor(viewport.width);
        canvas.height = Math.floor(viewport.height);
        const render = page.render({ canvas, viewport });
        cancelRender = () => render.cancel();
        await render.promise;

        let boxes: Box[] = [];
        if (citation.quote && pageNumber === citation.page) {
          const content = await page.getTextContent();
          const runs: TextRun[] = [];
          for (const item of content.items) {
            if (!("str" in item) || !item.str) continue;
            const m = pdfjs.Util.transform(base.transform, item.transform);
            const height = Math.hypot(m[2], m[3]);
            runs.push({ str: item.str, x: m[4], top: m[5] - height, width: item.width, height: height * 1.25 });
          }
          boxes = locateQuote(runs, citation.quote).map((b) => ({
            x: (b.x / base.width) * 100,
            top: (b.top / base.height) * 100,
            width: (b.width / base.width) * 100,
            height: (b.height / base.height) * 100,
          }));
        }
        if (!cancelled) setView({ boxes });
      } catch {
        if (!cancelled) setError("This page could not be displayed.");
      }
    })();
    return () => {
      cancelled = true;
      cancelRender?.();
    };
  }, [pdf, pageNumber, citation]);

  useEffect(() => {
    firstBoxRef.current?.scrollIntoView({ block: "center", inline: "start" });
  }, [view, zoomed]);

  const onCitedPage = pageNumber === citation.page;
  return (
    <dialog
      ref={dialogRef}
      className="evidence-dialog"
      aria-label="Evidence in the original document"
      onClose={onClose}
      // A click on the dialog element itself can only be on its backdrop
      onClick={(event) => event.target === dialogRef.current && dialogRef.current.close()}
    >
      <div className="evidence-layout">
        <header className="evidence-header">
          <div className="evidence-toolbar">
            <span className="page-label">
              Page {pageNumber}
              {pdf ? ` / ${pdf.numPages}` : ""}
            </span>
            <button
              type="button"
              aria-label="Previous page"
              disabled={pageNumber <= 1}
              onClick={() => setPageNumber((n) => n - 1)}
            >
              ‹
            </button>
            <button
              type="button"
              aria-label="Next page"
              disabled={!pdf || pageNumber >= pdf.numPages}
              onClick={() => setPageNumber((n) => n + 1)}
            >
              ›
            </button>
            <button type="button" aria-pressed={zoomed} onClick={() => setZoomed((z) => !z)}>
              {zoomed ? "Fit" : "Zoom"}
            </button>
            {!onCitedPage && (
              <button type="button" onClick={() => setPageNumber(citation.page)}>
                Back to p. {citation.page}
              </button>
            )}
            <button type="button" onClick={() => dialogRef.current?.close()}>
              Close
            </button>
          </div>
          {citation.quote && <blockquote className="reference-quote">{citation.quote}</blockquote>}
          {onCitedPage && citation.quote && view && view.boxes.length === 0 && (
            <p className="muted small">The quote could not be marked on this page; its text is shown above.</p>
          )}
          {error && (
            <p className="callout warning small" role="alert">
              {error}
            </p>
          )}
        </header>
        <div className="evidence-scroll">
          <div className="pdf-page" style={zoomed ? { width: `${ZOOM_FACTOR * 100}%` } : undefined}>
            <canvas ref={canvasRef} />
            {view?.boxes.map((box, i) => (
              <div
                key={i}
                ref={i === 0 ? firstBoxRef : undefined}
                className="pdf-highlight"
                style={{
                  left: `${box.x}%`,
                  top: `${box.top}%`,
                  width: `${box.width}%`,
                  height: `${box.height}%`,
                }}
              />
            ))}
          </div>
        </div>
      </div>
    </dialog>
  );
}
