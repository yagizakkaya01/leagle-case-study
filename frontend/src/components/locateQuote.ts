// Finds a cited quote among a PDF page's text runs and returns where to highlight it.
// The quote is verified against text extracted by another library, so spacing, line-end
// hyphens, ligatures and case can differ: matching looks at letters and digits only.

export interface TextRun {
  str: string;
  x: number;
  top: number;
  width: number;
  height: number;
}

export interface Box {
  x: number;
  top: number;
  width: number;
  height: number;
}

const MIN_PARTIAL_WORDS = 3;

function fold(text: string): string {
  return text
    .normalize("NFKD")
    .toLowerCase()
    .replace(/ı/g, "i")
    .replace(/[^\p{L}\p{N}]/gu, "");
}

// A shortened quote ("first part ... last part"): the longest run of its words on the page
function findRange(page: string, quote: string): [number, number] | null {
  const whole = fold(quote);
  if (!whole) return null;
  const exact = page.indexOf(whole);
  if (exact !== -1) return [exact, exact + whole.length];

  const words = quote.split(/\s+/).map(fold).filter(Boolean);
  for (let size = words.length - 1; size >= MIN_PARTIAL_WORDS; size--) {
    for (let start = 0; start + size <= words.length; start++) {
      const part = words.slice(start, start + size).join("");
      const at = page.indexOf(part);
      if (at !== -1) return [at, at + part.length];
    }
  }
  return null;
}

function sameLine(a: Box, b: Box): boolean {
  return Math.abs(a.top - b.top) < a.height / 2;
}

export function locateQuote(runs: TextRun[], quote: string): Box[] {
  let page = "";
  const owners: { run: number; char: number }[] = [];
  runs.forEach((run, r) => {
    Array.from(run.str).forEach((ch, c) => {
      const folded = fold(ch);
      page += folded;
      for (let i = 0; i < folded.length; i++) owners.push({ run: r, char: c });
    });
  });

  const range = findRange(page, quote);
  if (!range) return [];

  // Characters of each run inside the match; widths are shared evenly within a run
  const spans = new Map<number, { from: number; to: number }>();
  for (const { run, char } of owners.slice(range[0], range[1])) {
    const span = spans.get(run);
    if (span) span.to = char;
    else spans.set(run, { from: char, to: char });
  }

  const boxes: Box[] = [];
  for (const [r, { from, to }] of spans) {
    const run = runs[r];
    const chars = Array.from(run.str);
    const perChar = run.width / Math.max(chars.length, 1);
    // Matching skipped punctuation; keep what directly follows the last matched word
    let end = to;
    while (end + 1 < chars.length && /[^\p{L}\p{N}\s]/u.test(chars[end + 1])) end++;
    const box = { x: run.x + from * perChar, top: run.top, width: (end - from + 1) * perChar, height: run.height };
    const last = boxes[boxes.length - 1];
    if (last && sameLine(last, box) && box.x >= last.x) {
      last.width = box.x + box.width - last.x;
    } else {
      boxes.push(box);
    }
  }
  return boxes;
}
