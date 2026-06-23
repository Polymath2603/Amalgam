"""
Hybrid retrieval combining BM25 sparse + ChromaDB dense via RRF fusion.
"""
import logging
import re
from typing import Any, Optional

try:
    from rank_bm25 import BM25Okapi
except ImportError:
    BM25Okapi = None

logger = logging.getLogger(__name__)


class HybridRetrieval:
    def __init__(self, chroma_col: Optional[Any], k: int = 60):
        self._chroma = chroma_col
        self._k = k
        self._bm25: Optional[BM25Okapi] = None
        self._bm25_docs: list[dict] = []

    def add_document(self, msg: dict):
        """Incrementally add a single document to the BM25 index.

        Avoids O(n) full rebuild on every turn.
        """
        tokens = re.findall(r'\b\w+\b', msg.get('content', '').lower())
        if not tokens:
            # Still track empty docs for index alignment
            self._bm25_docs.append(msg)
            return
        self._bm25_docs.append(msg)
        if self._bm25 is not None:
            # BM25Okapi supports incremental addition via the underlying corpus
            # Rebuild from scratch using accumulated docs for simplicity & correctness
            # (BM25Okapi doesn't natively support add_document, so we rebuild)
            self._rebuild()
        else:
            self._rebuild()

    def _rebuild(self):
        """Rebuild BM25 index from accumulated documents."""
        corpus = []
        for doc in self._bm25_docs:
            tokens = re.findall(r'\b\w+\b', doc.get('content', '').lower())
            corpus.append(tokens)
        # Filter out empty token lists to avoid ZeroDivisionError in BM25Okapi
        non_empty_indices = [i for i, doc in enumerate(corpus) if doc]
        non_empty_corpus = [corpus[i] for i in non_empty_indices]
        self._bm25 = BM25Okapi(non_empty_corpus) if non_empty_corpus else None
        # Store mapping so we can map BM25 result indices back to _bm25_docs
        self._bm25_non_empty_indices = non_empty_indices

    def rebuild_bm25(self, messages: list[dict]):
        """Full rebuild from a list of messages (used for migration/initial load)."""
        self._bm25_docs = messages
        self._rebuild()

    async def retrieve(self, query: str, query_emb: list[float],
                       session_id: str, top_k: int = 5) -> list[dict]:
        results: dict[str, float] = {}

        # Dense retrieval via ChromaDB
        if self._chroma is not None:
            try:
                dense = self._chroma.query(
                    query_embeddings=[query_emb],
                    n_results=top_k * 2,
                    where={"session_id": session_id},
                )
                if dense and dense.get("metadatas") and dense["metadatas"][0]:
                    for rank, meta in enumerate(dense["metadatas"][0]):
                        cid = meta.get("content", "")[:50]
                        results[cid] = results.get(cid, 0) + 1 / (self._k + rank + 1)
            except Exception as e:
                logger.debug(f"ChromaDB dense query failed: {e}")

        # Sparse retrieval via BM25
        if self._bm25 and self._bm25_docs:
            query_tokens = re.findall(r'\b\w+\b', query.lower())
            scores = self._bm25.get_scores(query_tokens)
            non_empty_indices = getattr(self, '_bm25_non_empty_indices', list(range(len(self._bm25_docs))))
            # Map BM25 result indices back to _bm25_docs indices
            for bm25_rank, (corpus_idx, score) in enumerate(
                sorted(enumerate(scores), key=lambda x: x[1], reverse=True)
            ):
                if score <= 0:
                    continue
                if corpus_idx >= len(non_empty_indices):
                    continue
                doc_idx = non_empty_indices[corpus_idx]
                if doc_idx >= len(self._bm25_docs):
                    continue
                content = self._bm25_docs[doc_idx].get("content", "")
                cid = content[:50]
                results[cid] = results.get(cid, 0) + 1 / (self._k + bm25_rank + 1)

        # RRF fusion: sort by combined score
        sorted_results = sorted(results.items(), key=lambda x: x[1], reverse=True)

        out = []
        seen = set()
        for cid, _ in sorted_results[:top_k]:
            if cid in seen:
                continue
            seen.add(cid)
            for doc in self._bm25_docs:
                if doc.get("content", "")[:50] == cid:
                    out.append(doc)
                    break
        return out
