"""Runs the gold questions against the real model and prints a scored report.

    cd backend && python -m eval                 # all questions
    python -m eval --only fact-01,absent-02      # a subset
    python -m eval --workers 2                   # parallel requests (free endpoint: keep low)

Needs NVIDIA_API_KEY in backend/.env. Uses the production code path (same chunking,
metadata extraction, hybrid search, tools and citation checks), with in-memory
storage so nothing is written to a database. Results are saved to eval/results/.
"""
from __future__ import annotations

import argparse
import json
import math
import sys
import tempfile
import time
import uuid
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from pathlib import Path

from app.config import settings
from app.llm import get_chat_model, get_embeddings
from app.services.chat import ChatService
from app.services.document_metadata import build_extractor
from app.services.document_store import DocumentStore, StoredDocument
from app.services.file_storage import LocalFileStorage
from app.services.persistence import MemoryRepository
from app.services.text_normalize import to_ascii
from eval.documents import DOCUMENTS
from eval.gold import GOLD
from tests.pdf_factory import make_pdf

RESULTS_DIR = Path(__file__).parent / "results"


def wilson(c: int, n: int, z: float = 1.96) -> tuple[float, float]:
    """Wilson 95% interval for a proportion; meaningful for small n and at 0/n or n/n."""
    if n == 0:
        return 0.0, 0.0
    p = c / n
    den = 1 + z * z / n
    mid = (p + z * z / (2 * n)) / den
    half = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / den
    return max(0.0, mid - half), min(1.0, mid + half)


def rate(c: int, n: int) -> str:
    lo, hi = wilson(c, n)
    pct = 100 * c / n if n else 0.0
    return f"{c:>2}/{n:<2} {pct:5.1f}%  [95% CI {100 * lo:4.1f}-{100 * hi:5.1f}]"


def _contains(answer: str, needle: str) -> bool:
    return to_ascii(needle) in to_ascii(answer)


def score(gold: dict, answer) -> dict:
    text = answer.answer
    groups_ok = all(any(_contains(text, alt) for alt in group) for group in gold["must_contain"])
    forbidden = [s for s in gold["must_not"] if _contains(text, s)]
    if gold["found"]:
        page_ok = answer.found and answer.page_number == gold["page"]
        passed = groups_ok and page_ok and not forbidden
    else:
        page_ok = None
        passed = not answer.found and not forbidden
    return {"passed": passed, "answer_ok": groups_ok and not forbidden, "page_ok": page_ok,
            "hallucinated": (not gold["found"]) and answer.found, "forbidden": forbidden}


def run_one(chat: ChatService, docs: dict[str, StoredDocument], gold: dict) -> dict:
    doc = docs[gold["doc"]]
    conversation = str(uuid.uuid4())
    for attempt in (1, 2):  # one retry for provider errors; they don't count as wrong
        try:
            for earlier in gold["history"]:
                chat.ask(doc, conversation, earlier)
            started = time.perf_counter()
            answer = chat.ask(doc, conversation, gold["question"])
            latency = time.perf_counter() - started
            break
        except Exception as exc:  # noqa: BLE001 - provider timeouts, 5xx
            if attempt == 2:
                return {"id": gold["id"], "category": gold["category"], "infra_error": str(exc)}
            conversation = str(uuid.uuid4())
    return {
        "id": gold["id"], "category": gold["category"], "question": gold["question"],
        "expected_page": gold["page"], "page": answer.page_number, "found": answer.found,
        "answer": answer.answer, "reference_text": answer.reference_text,
        "tools": [t.name for t in answer.tool_calls], "latency": round(latency, 2),
        **score(gold, answer),
    }


def report(records: list[dict]) -> str:
    errors = [r for r in records if "infra_error" in r]
    scored = [r for r in records if "infra_error" not in r]
    present = [r for r in scored if r["page_ok"] is not None]
    absent = [r for r in scored if r["page_ok"] is None]
    effort = settings.LLM_REASONING_EFFORT or "-"
    lines = [
        f"model: {settings.NVIDIA_MODEL} (reasoning effort: {effort})",
        f"questions: {len(records)}  scored: {len(scored)}  provider errors: {len(errors)}",
        "",
        f"overall pass        {rate(sum(r['passed'] for r in scored), len(scored))}",
        f"answer correct      {rate(sum(r['answer_ok'] for r in present), len(present))}"
        "  (in-document questions)",
        f"page correct        {rate(sum(bool(r['page_ok']) for r in present), len(present))}",
        f"says 'not in doc'   {rate(sum(r['passed'] for r in absent), len(absent))}"
        "  (questions the document cannot answer)",
        f"hallucinated cites  {sum(r['hallucinated'] for r in absent)}",
        "",
        "by category:",
    ]
    by_cat: dict[str, list[bool]] = defaultdict(list)
    for r in scored:
        by_cat[r["category"]].append(r["passed"])
    for cat, results in sorted(by_cat.items()):
        lines.append(f"  {cat:<10} {rate(sum(results), len(results))}")
    lat = sorted(r["latency"] for r in scored)
    if lat:
        def pct(p: float) -> float:
            return lat[min(len(lat) - 1, int(p * len(lat)))]
        lines += ["", f"latency: p50 {pct(0.5):.1f}s  p95 {pct(0.95):.1f}s  max {lat[-1]:.1f}s"]
    failures = [r for r in scored if not r["passed"]]
    if failures:
        lines += ["", "failures:"]
        for r in failures:
            lines.append(f"  {r['id']}: page {r['page']} (expected {r['expected_page']}), "
                         f"found={r['found']}, tools={r['tools']}")
            lines.append(f"      {r['answer'][:160]}")
    for r in errors:
        lines.append(f"  {r['id']}: PROVIDER ERROR {r['infra_error'][:120]}")
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--only", help="comma-separated question ids")
    parser.add_argument("--workers", type=int, default=2)
    args = parser.parse_args()

    llm = get_chat_model()
    if llm is None:
        sys.exit("NVIDIA_API_KEY is not set in backend/.env")
    repo = MemoryRepository()
    store = DocumentStore(LocalFileStorage(Path(tempfile.mkdtemp())),
                          chunk_size=settings.CHUNK_SIZE, overlap=settings.CHUNK_OVERLAP,
                          max_pages=settings.MAX_PAGES, metadata_extractor=build_extractor(llm),
                          embeddings=get_embeddings(), repository=repo)
    docs = {key: store.add(make_pdf(pages), name) for key, (name, pages) in DOCUMENTS.items()}
    chat = ChatService(llm, repo.history)

    wanted = set(args.only.split(",")) if args.only else None
    gold = [g for g in GOLD if wanted is None or g["id"] in wanted]
    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        records = list(pool.map(lambda g: run_one(chat, docs, g), gold))

    text = report(records)
    print(text)
    RESULTS_DIR.mkdir(exist_ok=True)
    out = RESULTS_DIR / f"{datetime.now():%Y%m%d-%H%M%S}.json"
    out.write_text(json.dumps({"model": settings.NVIDIA_MODEL, "records": records,
                               "report": text}, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"\nsaved {out}")


if __name__ == "__main__":
    main()
