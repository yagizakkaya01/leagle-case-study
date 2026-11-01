"""Finds where a cited quote sits on its PDF page, to highlight it in the viewer.

The search runs on the same pdfplumber lines the quote was extracted from, so
reading order, columns and font encodings cannot differ between the two, and
each box comes from real character positions.
"""
from __future__ import annotations

import io
import unicodedata

import pdfplumber
from rapidfuzz import fuzz

from app.schemas import HighlightBox
from app.services.grounding import QUOTE_MATCH_THRESHOLD
from app.services.pdf_processing import X_TOLERANCE


def _fold(text: str) -> str:
    """Letters and digits only: spacing, hyphens, ligatures and case do not matter."""
    decomposed = unicodedata.normalize("NFKD", text.replace("ı", "i").replace("İ", "i"))
    return "".join(c for c in decomposed.casefold() if c.isalnum())


def _find(page_text: str, quote: str) -> tuple[int, int] | None:
    start = page_text.find(quote)
    if start != -1:
        return start, start + len(quote)
    # The quote passed grounding with the same measure, so it may differ slightly.
    match = fuzz.partial_ratio_alignment(quote, page_text, score_cutoff=QUOTE_MATCH_THRESHOLD)
    return (match.dest_start, match.dest_end) if match else None


def _visible_frame(page: pdfplumber.page.Page) -> tuple[float, float, float, float]:
    """(left, top, width, height) of what a PDF viewer shows, in the characters' coordinates.

    A viewer shows the crop box inside the media box, turned by the page's rotation.
    pdfplumber's own cropbox does not line up with its characters on rotated pages or when
    the media box does not start at zero, so the frame is worked out from the raw boxes.
    tests/test_quote_location.py pins this to where pdf.js draws the same pages.
    """
    mx0, my0, mx1, my1 = page.page_obj.mediabox
    cx0, cy0, cx1, cy1 = page.page_obj.cropbox
    x0, y0, x1, y1 = max(cx0, mx0), max(cy0, my0), min(cx1, mx1), min(cy1, my1)
    rotation = page.rotation % 360
    if rotation == 90:
        return y0, x0 - 2 * mx0, y1 - y0, x1 - x0
    if rotation == 180:
        return mx0 + mx1 - x1, y0 - 2 * my0, x1 - x0, y1 - y0
    if rotation == 270:
        return my0 + my1 - y1, mx1 - mx0 - x1, y1 - y0, x1 - x0
    return x0, my1 - my0 - y1, x1 - x0, y1 - y0


def _boxes(chars: list[dict], page: pdfplumber.page.Page) -> list[HighlightBox]:
    """One box per run of neighbouring characters; table cells on a line stay separate."""
    left, top, width, height = _visible_frame(page)
    runs: list[list[float]] = []
    line = None
    for c in chars:
        run = runs[-1] if runs else None
        if run and c["line"] == line and c["x0"] - run[2] < c["bottom"] - c["top"]:
            run[0], run[1] = min(run[0], c["x0"]), min(run[1], c["top"])
            run[2], run[3] = max(run[2], c["x1"]), max(run[3], c["bottom"])
        else:
            runs.append([c["x0"], c["top"], c["x1"], c["bottom"]])
        line = c["line"]
    return [
        HighlightBox(
            x=(x0 - left) / width * 100,
            top=(y0 - top) / height * 100,
            width=(x1 - x0) / width * 100,
            height=(y1 - y0) / height * 100,
        )
        for x0, y0, x1, y1 in runs
    ]


def locate_quote(data: bytes, page_number: int, quote: str) -> list[HighlightBox]:
    """Boxes in percent of the page, or an empty list when the quote is not on it."""
    target = _fold(quote)
    if not target:
        return []
    with pdfplumber.open(io.BytesIO(data)) as pdf:
        if not 1 <= page_number <= len(pdf.pages):
            return []
        page = pdf.pages[page_number - 1]

        chars: list[dict] = []
        page_text = ""
        owners: list[int] = []  # for each folded character, its index in `chars`
        for number, line in enumerate(page.extract_text_lines(x_tolerance=X_TOLERANCE)):
            for char in line["chars"]:
                folded = _fold(char["text"])
                page_text += folded
                owners.extend([len(chars)] * len(folded))
                chars.append({**char, "line": number})

        found = _find(page_text, target) if page_text else None
        if found is None or found[0] == found[1]:
            return []
        first, last = owners[found[0]], owners[found[1] - 1]
        # Matching skipped punctuation; keep what directly follows the last matched word
        while (last + 1 < len(chars) and chars[last + 1]["line"] == chars[last]["line"]
               and not chars[last + 1]["text"].isspace() and not _fold(chars[last + 1]["text"])):
            last += 1
        return _boxes(chars[first:last + 1], page)
