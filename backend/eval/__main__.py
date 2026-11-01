"""Runs gold questions against the real model and prints a scored report.

    cd backend && python -m eval                      # basic set (30 questions)
    python -m eval --set hard --repeat 3              # hard set, each question 3 times
    python -m eval --only fact-01,absent-02           # a subset
    python -m eval --workers 2                        # parallel requests (keep low)

Needs NVIDIA_API_KEY in backend/.env. Uses the production code path (same chunking,
metadata extraction, hybrid search, tools and citation checks), with in-memory
storage so nothing is written to a database. Results are saved to eval/results/.

Outcome labels follow the legal-RAG hallucination study by Magesh et al. (2025):
accurate, misgrounded (right answer, wrong source), incorrect, refusal; for questions
the document cannot answer, correct_refusal or hallucinated.
"""
from __future__ import annotations

import argparse
import json
import math
import re
import sys
import tempfile
import time
import uuid
from collections import Counter, defaultdict
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from pathlib import Path

from app.config import settings
from app.llm import get_chat_model, get_embeddings, get_reranker
from app.services.chat import ChatService
from app.services.document_metadata import build_extractor
from app.services.document_store import DocumentStore, StoredDocument
from app.services.file_storage import LocalFileStorage
from app.services.persistence import MemoryRepository
from app.services.text_normalize import to_ascii
from eval.documents import DOCUMENTS
from eval.gold import GOLD
from eval.gold_hard import GOLD_HARD
from eval.gold_heldout import GOLD_HELDOUT
from tests.pdf_factory import make_pdf

RESULTS_DIR = Path(__file__).parent / "results"
SETS = {"basic": GOLD, "hard": GOLD_HARD, "heldout": GOLD_HELDOUT}
# Seconds before each attempt. The free endpoint's limit clears within minutes; retrying at
# once would spend a whole set on 429s. Latency is timed per attempt, so waits don't count.
PROVIDER_RETRY_WAITS = (0, 60, 120, 240, 300, 300)


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
    """Whole-word, case- and accent-insensitive match ("no" must not match "notice")."""
    pattern = rf"(?<!\w){re.escape(to_ascii(needle))}(?!\w)"
    return re.search(pattern, to_ascii(answer)) is not None


def score(gold: dict, answer) -> dict:
    text = answer.answer
    facts_ok = all(any(_contains(text, alt) for alt in group) for group in gold["must_contain"])
    forbidden = [s for s in gold["must_not"] if _contains(text, s)]
    if gold["found"]:
        page_ok = answer.found and answer.page_number in gold["pages"]
        if not answer.found:
            outcome = "refusal"
        elif facts_ok and not forbidden:
            outcome = "accurate" if page_ok else "misgrounded"
        else:
            outcome = "incorrect"
    else:
        page_ok = None
        outcome = "correct_refusal" if not answer.found and not forbidden else "hallucinated"
    tools = [t.name for t in answer.tool_calls]
    return {
        "passed": outcome in ("accurate", "correct_refusal"), "outcome": outcome,
        "answer_ok": facts_ok and not forbidden, "page_ok": page_ok, "forbidden": forbidden,
        "tool_ok": None if not gold.get("tool") else gold["tool"] in tools,
    }


def _is_infra_error(exc: Exception) -> bool:
    """Provider-side problems (timeouts, 429, 5xx) are retried and reported apart;
    any other HTTP 4xx means the request we built was invalid and counts as a failure."""
    status = re.search(r"\[(\d{3})\]", str(exc))
    if status is None:
        return True  # timeouts and connection errors carry no status code
    code = int(status.group(1))
    return code == 429 or code >= 500


def run_one(chat: ChatService, docs: dict[str, StoredDocument], gold: dict, run: int) -> dict:
    doc = docs[gold["doc"]]
    base = {"id": gold["id"], "run": run, "category": gold["category"],
            "failure_mode": gold.get("failure_mode")}
    for attempt, wait in enumerate(PROVIDER_RETRY_WAITS, start=1):  # they don't count as wrong
        time.sleep(wait)
        conversation = str(uuid.uuid4())
        try:
            for earlier in gold["history"]:
                chat.ask(doc, conversation, earlier)
            # The streaming path is what the UI uses: time to the first progress event
            # is what a user waits before seeing anything happen.
            started = time.perf_counter()
            first_event = None
            for event in chat.ask_stream(doc, conversation, gold["question"]):
                if first_event is None:
                    first_event = time.perf_counter() - started
                if event["type"] == "final":
                    answer = event["answer"]
            latency = time.perf_counter() - started
            break
        except Exception as exc:  # noqa: BLE001
            if not _is_infra_error(exc):  # e.g. HTTP 400: our request was wrong
                return {**base, "question": gold["question"], "expected_pages": gold["pages"],
                        "page": None, "found": False, "answer": f"ERROR: {exc}"[:300],
                        "reference_text": None, "tools": [], "latency": 0.0,
                        "first_event": 0.0, "tool_count": 0, "passed": False,
                        "outcome": "error", "answer_ok": False,
                        "page_ok": False if gold["found"] else None, "forbidden": [],
                        "tool_ok": False if gold.get("tool") else None}
            if attempt == len(PROVIDER_RETRY_WAITS):
                return {**base, "infra_error": str(exc)}
    return {
        **base, "question": gold["question"], "expected_pages": gold["pages"],
        "page": answer.page_number, "found": answer.found, "answer": answer.answer,
        "reference_text": answer.reference_text,
        "sources": [s.model_dump() for s in answer.sources],
        "tools": [t.name for t in answer.tool_calls],
        "latency": round(latency, 2), "first_event": round(first_event or latency, 2),
        "tool_count": len(answer.tool_calls), **score(gold, answer),
    }


def pass_hat_k(records: list[dict]) -> tuple[int, int]:
    """τ-bench style pass^k: questions answered correctly in every one of their runs."""
    runs: dict[str, list[bool]] = defaultdict(list)
    for r in records:
        runs[r["id"]].append(r["passed"])
    return sum(all(v) for v in runs.values()), len(runs)


def _spread(values: list[float]) -> str:
    v = sorted(values)

    def pct(p: float) -> float:
        return v[min(len(v) - 1, int(p * len(v)))]
    return (f"p50 {pct(0.5):5.1f}s  p95 {pct(0.95):5.1f}s  max {v[-1]:5.1f}s  "
            f"mean {sum(v) / len(v):5.1f}s")


def report(records: list[dict], gold_set: str, repeat: int) -> str:
    errors = [r for r in records if "infra_error" in r]
    scored = [r for r in records if "infra_error" not in r]
    present = [r for r in scored if r["page_ok"] is not None]
    absent = [r for r in scored if r["page_ok"] is None]
    lines = [
        f"set: {gold_set}   model: {settings.NVIDIA_MODEL} "
        f"(reasoning effort: {settings.LLM_REASONING_EFFORT or '-'})",
        f"answers: {len(records)} ({repeat} run(s) per question)  scored: {len(scored)}  "
        f"provider errors: {len(errors)}",
        "",
        f"pass^1 (all answers)  {rate(sum(r['passed'] for r in scored), len(scored))}",
    ]
    if repeat > 1:
        c, n = pass_hat_k(scored)
        lines.append(f"pass^{repeat} (every run)    {rate(c, n)}")
    lines += [
        f"answer correct        {rate(sum(r['answer_ok'] for r in present), len(present))}",
        f"page correct          {rate(sum(bool(r['page_ok']) for r in present), len(present))}",
        f"says 'not in doc'     {rate(sum(r['passed'] for r in absent), len(absent))}",
    ]
    tooled = [r for r in scored if r["tool_ok"] is not None]
    if tooled:
        used = sum(r["tool_ok"] for r in tooled)
        lines.append(f"expected tool used    {rate(used, len(tooled))}")
    outcomes = Counter(r["outcome"] for r in scored)
    lines += ["", "outcomes: " + ", ".join(f"{k} {v}" for k, v in sorted(outcomes.items()))]

    key = "category" if gold_set == "basic" else "failure_mode"
    groups: dict[str, list[bool]] = defaultdict(list)
    for r in scored:
        groups[r[key] or "-"].append(r["passed"])
    lines += ["", f"by {key.replace('_', ' ')}:"]
    for name, results in sorted(groups.items()):
        lines.append(f"  {name:<14} {rate(sum(results), len(results))}")

    if scored:
        lines += ["", "speed:",
                  f"  first progress  {_spread([r['first_event'] for r in scored])}",
                  f"  full answer     {_spread([r['latency'] for r in scored])}",
                  f"  tool calls per answer: "
                  f"{sum(r['tool_count'] for r in scored) / len(scored):.1f} on average"]

    failures = [r for r in scored if not r["passed"]]
    if failures:
        lines += ["", "failures:"]
        for r in failures:
            lines.append(f"  {r['id']} (run {r['run']}): {r['outcome']}, page {r['page']} "
                         f"(expected {r['expected_pages'] or 'none'}), tools={r['tools']}")
            lines.append(f"      {r['answer'][:180]}")
    for r in errors:
        lines.append(f"  {r['id']} (run {r['run']}): PROVIDER ERROR {r['infra_error'][:120]}")
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--set", choices=sorted(SETS), default="basic", dest="gold_set")
    parser.add_argument("--repeat", type=int, default=1, help="runs per question (pass^k)")
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
                          embeddings=get_embeddings(), reranker=get_reranker(), repository=repo)
    gold = [g for g in SETS[args.gold_set]
            if not args.only or g["id"] in args.only.split(",")]
    needed = {g["doc"] for g in gold}
    docs = {key: store.add(make_pdf(pages), name)
            for key, (name, pages) in DOCUMENTS.items() if key in needed}
    chat = ChatService(llm, repo.history)

    jobs = [(g, run) for run in range(1, args.repeat + 1) for g in gold]
    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        records = list(pool.map(lambda job: run_one(chat, docs, *job), jobs))

    text = report(records, args.gold_set, args.repeat)
    print(text)
    RESULTS_DIR.mkdir(exist_ok=True)
    out = RESULTS_DIR / f"{datetime.now():%Y%m%d-%H%M%S}-{args.gold_set}.json"
    out.write_text(json.dumps({"set": args.gold_set, "model": settings.NVIDIA_MODEL,
                               "repeat": args.repeat, "records": records, "report": text},
                              ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"\nsaved {out}")


if __name__ == "__main__":
    main()
