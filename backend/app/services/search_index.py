"""Hybrid search over one document's chunks: BM25 + embeddings, merged with RRF.

BM25 catches exact legal terms ("Madde 7", "force majeure"); embeddings catch
paraphrases. Without an embedding model the index runs on BM25 alone.
"""
from __future__ import annotations

import logging
import re
from collections.abc import Callable

from langchain_core.documents import Document
from langchain_core.embeddings import Embeddings
from langchain_core.vectorstores import InMemoryVectorStore
from rank_bm25 import BM25Plus

from app.services.text_normalize import to_ascii

log = logging.getLogger(__name__)

ChunkFilter = Callable[[Document], bool]
_RRF_K = 60


def tokenize(text: str) -> list[str]:
    # Keeps hyphens ("Depo-3", "non-disclosure"); Turkish-aware lower-casing.
    return re.sub(r"[^\w\s\-]", " ", to_ascii(text)).split()


def rrf_merge(*rankings: list[str], k: int = _RRF_K) -> list[str]:
    """Reciprocal Rank Fusion: score = sum of 1 / (k + rank) over the rankings."""
    scores: dict[str, float] = {}
    for ranking in rankings:
        for rank, chunk_id in enumerate(ranking):
            scores[chunk_id] = scores.get(chunk_id, 0.0) + 1.0 / (k + rank + 1)
    return sorted(scores, key=scores.__getitem__, reverse=True)


class SearchIndex:
    def __init__(self, chunks: list[Document], embeddings: Embeddings | None = None):
        self._chunks = {c.metadata["chunk_id"]: c for c in chunks}
        self._order = list(self._chunks)
        tokens = [tokenize(c.page_content) for c in chunks]
        # BM25Plus keeps term weights positive: BM25Okapi scores a term found in half
        # of a 2-chunk document as 0, so short PDFs returned no keyword hits at all.
        self._bm25 = BM25Plus(tokens) if chunks else None
        self._vocab = {cid: set(t) for cid, t in zip(self._order, tokens, strict=True)}
        self._vectors: InMemoryVectorStore | None = None
        if embeddings is not None and chunks:
            try:
                self._vectors = InMemoryVectorStore(embeddings)
                self._vectors.add_documents(chunks, ids=self._order)
            except Exception:  # search still works on BM25 alone
                log.warning("Embedding the chunks failed; using keyword search only",
                            exc_info=True)
                self._vectors = None

    def search(self, query: str, k: int = 5, where: ChunkFilter | None = None) -> list[Document]:
        if self._bm25 is None:
            return []
        allowed = where or (lambda _: True)
        candidates = max(k * 3, 10)

        query_tokens = tokenize(query)
        scores = self._bm25.get_scores(query_tokens)
        keyword = [cid for cid, _ in sorted(zip(self._order, scores, strict=True),
                                            key=lambda p: p[1], reverse=True)
                   if self._vocab[cid].intersection(query_tokens)
                   and allowed(self._chunks[cid])][:candidates]

        semantic: list[str] = []
        if self._vectors is not None:
            try:
                hits = self._vectors.similarity_search(query, k=candidates, filter=allowed)
                semantic = [h.metadata["chunk_id"] for h in hits]
            except Exception:
                log.warning("Semantic search failed; using keyword results", exc_info=True)

        return [self._chunks[cid] for cid in rrf_merge(semantic, keyword)[:k]]
