"""Rule-based metadata for chunks: section headings, clause categories, references.

No LLM is involved, so every value here is deterministic and cheap; the tool
layer filters on these fields instead of trusting the model to find them.
"""
from __future__ import annotations

import re

from app.services.text_normalize import normalize_whitespace, to_ascii

# --- Headings -----------------------------------------------------------------
# Each pattern captures the clause number in group "num".
_HEADING_PATTERNS = [
    re.compile(r"^(?:madde|article|section|bolum|clause)\s+(?P<num>\d+(?:\.\d+)*|[ivxlc]+)\b"),
    re.compile(r"^(?P<num>\d+(?:\.\d+)*)[.)]?\s+\S"),
]
_MAX_HEADING_CHARS = 90
_MAX_HEADING_WORDS = 12


def parse_heading(line: str, *, large_font: bool = False) -> tuple[str, str | None] | None:
    """Returns (heading, clause_number) when the line looks like a heading.

    `large_font` marks a line set in a bigger font than the body text, which is
    how many documents show headings that have no number or capitals.
    """
    line = normalize_whitespace(line)
    if not line or len(line) > _MAX_HEADING_CHARS or len(line.split()) > _MAX_HEADING_WORDS:
        return None

    folded = to_ascii(line)
    for pattern in _HEADING_PATTERNS:
        match = pattern.match(folded)
        if match:
            if pattern is _HEADING_PATTERNS[1] and _is_numbered_body_line(line, match):
                return None
            return line, match.group("num")

    letters = [c for c in line if c.isalpha()]
    if large_font or (len(letters) >= 4 and all(c.isupper() for c in letters)):
        return line, None
    # "AMENDMENT No. 1 (signed ...)", "SIDE LETTER dated ...": a capitalised lead-in.
    if _CAPS_LEAD.match(line):
        return line, None
    return None


def _is_numbered_body_line(line: str, match: re.Match[str]) -> bool:
    """A line starting with a number that reads as body text, not as a clause heading."""
    # Numbered list items usually end with a full stop; headings do not.
    if line.endswith((".", ";", ",")):
        return True
    # A wrapped line can start with an amount, a year or a count ("18.500 TL tutarındaki",
    # "2024 tarihinde", "30 percent of the fee"). Clause numbers have at most two digits
    # per part and are followed by a capitalised title. Digits and dots are the same in
    # the folded text the match ran on, so its position also holds in `line`.
    if any(len(part) >= 3 for part in match.group("num").split(".")):
        return True
    return line[match.end("num"):].lstrip(".) ")[:1].islower()


# At the start of a line: two or more all-caps words ("SIDE LETTER dated ..."), or one of
# six letters or more that is not followed by a lower-case word ("AMENDMENT No. 1" is a
# heading, "LICENSEE shall bear all costs" is a sentence).
_CAPS_LEAD = re.compile(
    r"^(?:[A-ZÇĞİÖŞÜ]{2,}\s+[A-ZÇĞİÖŞÜ]{2,}\b|[A-ZÇĞİÖŞÜ]{6,}\b(?!\s+[a-zçğıöşü]))"
)


# --- Clause categories ----------------------------------------------------------
# Keywords are matched on `to_ascii` text, so Turkish ones are written without
# Turkish letters. Heading hits count double: a heading names the clause.
CLAUSE_KEYWORDS: dict[str, tuple[str, ...]] = {
    "definitions": ("definition", "tanim", "means", "ifade eder"),
    "payment": ("payment", "fee", "price", "rent", "invoice", "odeme", "ucret", "bedel",
                "kira bedeli", "fatura"),
    "term_duration": ("term of", "duration", "commencement", "sure", "yururluk"),
    "termination": ("terminat", "fesih", "feshi", "sona erme", "sona erer"),
    "obligations": ("obligation", "shall perform", "yukumluluk", "borclari", "taahhut"),
    "confidentiality": ("confidential", "non-disclosure", "gizlilik", "sir saklama"),
    "liability_indemnity": ("liabilit", "indemn", "damages", "sorumluluk", "tazminat",
                            "zarar"),
    "force_majeure": ("force majeure", "act of god", "mucbir sebep"),
    "governing_law": ("governing law", "applicable law", "uygulanacak hukuk",
                      "governed by", "laws of", "hukuku uygulan"),
    "dispute_resolution": ("dispute", "arbitration", "jurisdiction", "court", "uyusmazlik",
                           "tahkim", "yetkili mahkeme", "icra daire"),
    "intellectual_property": ("intellectual property", "copyright", "trademark", "patent",
                              "fikri mulkiyet", "telif"),
    "data_protection": ("personal data", "gdpr", "data protection", "kisisel veri", "kvkk"),
}
OTHER = "other"

# Keywords match at a word start ("terminat" hits "termination", "sure" misses "ensure").
_KEYWORD_RES = {
    category: [re.compile(rf"\b{re.escape(k)}") for k in keywords]
    for category, keywords in CLAUSE_KEYWORDS.items()
}


def classify_clause(heading: str | None, text: str) -> str:
    heading_folded = to_ascii(heading or "")
    text_folded = to_ascii(text)
    best, best_score = OTHER, 0
    for category, patterns in _KEYWORD_RES.items():
        score = sum(2 for p in patterns if p.search(heading_folded))
        score += sum(1 for p in patterns if p.search(text_folded))
        if score > best_score:
            best, best_score = category, score
    # A single keyword in body text is too weak a signal on its own.
    return best if best_score >= 2 else OTHER


# --- Cross-references -----------------------------------------------------------------
# "clause 3", "clauses 2 and 7", "Section 4.1", "Article 5", "Madde 3", "3. maddesi".
_NUM = r"\d+(?:\.\d+)*"
_REF_AFTER = re.compile(
    rf"\b(?:clauses?|sections?|articles?|paragraphs?|madde\w*)\s+"
    rf"({_NUM}(?:\s*(?:,|and|or|ve|veya|-|to)\s*{_NUM})*)"
)
_REF_BEFORE = re.compile(rf"\b({_NUM})\.?\s*madde")


def referenced_clauses(text: str, own: str | None = None) -> list[str]:
    """Clause numbers this text refers to, excluding its own clause."""
    folded = to_ascii(text)
    found = [n for m in _REF_AFTER.finditer(folded) for n in re.findall(_NUM, m.group(1))]
    found += _REF_BEFORE.findall(folded)
    return sorted({n for n in found if n != own}, key=lambda n: [int(x) for x in n.split(".")])


# --- Turkish court case numbers ---------------------------------------------------
# "Esas No: 2022/16696", "2022/16696 E.", "Karar No : 2024/1755", "2024/1755 K."
_CASE_NUMBER = re.compile(
    r"(?:esas\s*(?:no)?\s*[:.]?\s*(?P<e1>\d{4}/\d+))|(?P<e2>\d{4}/\d+)\s*e\.|"
    r"(?:karar\s*(?:no)?\s*[:.]?\s*(?P<k1>\d{4}/\d+))|(?P<k2>\d{4}/\d+)\s*k\.",
    re.IGNORECASE,
)
_CASE_NUMBER_EN = re.compile(r"\bcase\s+no\.?\s*[:]?\s*([\w/.\-]+\d)", re.IGNORECASE)


def case_numbers(text: str) -> list[str]:
    found: list[str] = []
    for m in _CASE_NUMBER.finditer(to_ascii(text)):
        if m.group("e1") or m.group("e2"):
            found.append(f"{m.group('e1') or m.group('e2')} E.")
        else:
            found.append(f"{m.group('k1') or m.group('k2')} K.")
    found.extend(f"Case No. {n}" for n in _CASE_NUMBER_EN.findall(text))
    return list(dict.fromkeys(found))  # de-duplicate, keep order
