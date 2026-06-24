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
        # Tokenized corpus maintained alongside _bm25_docs for efficient rebuilds
        self._tokenized_corpus: list[list[str]] = []
        # Rebuild batching: only rebuild every N add_document calls
        self._rebuild_batch_size = 10
        self._docs_since_rebuild = 0

    def add_document(self, msg: dict):
        """Incrementally add a single document to the BM25 index.

        To avoid O(n) full rebuild on every turn, tokenization happens inline
        and the BM25 index is fully rebuilt only every N turns.  The full
        tokenized corpus is kept in sync so _rebuild() is O(1) when triggered.
        """
        tokens = re.findall(r'\w+(?:[.:_]\w+)*', msg.get('content', '').lower())
        self._bm25_docs.append(msg)
        self._tokenized_corpus.append(tokens)
        self._docs_since_rebuild += 1

        if self._docs_since_rebuild >= self._rebuild_batch_size:
            self._rebuild()
            self._docs_since_rebuild = 0

        # Ensure BM25 is initialized after first doc even if batch not full
        if self._bm25 is None and tokens:
            self._rebuild()
            self._docs_since_rebuild = 0

    def _rebuild(self):
        """Rebuild BM25 index from accumulated tokenized corpus."""
        # Filter out empty token lists to avoid ZeroDivisionError in BM25Okapi
        non_empty_indices = [i for i, doc in enumerate(self._tokenized_corpus) if doc]
        non_empty_corpus = [self._tokenized_corpus[i] for i in non_empty_indices]
        self._bm25 = BM25Okapi(non_empty_corpus) if non_empty_corpus else None
        self._bm25_non_empty_indices = non_empty_indices

    def rebuild_bm25(self, messages: list[dict]):
        """Full rebuild from a list of messages (used for migration/initial load)."""
        self._bm25_docs = messages
        self._tokenized_corpus = [
            re.findall(r'\w+(?:[.:_]\w+)*', m.get('content', '').lower())
            for m in messages
        ]
        self._rebuild()
        self._docs_since_rebuild = 0

    async def retrieve(self, query: str, query_emb: list[float],
                       session_id: str, top_k: int = 5) -> list[dict]:
        results: dict[str, float] = {}

        # Dense retrieval via ChromaDB
        if self._chroma is not None:
            try:
                # ChromaDB's Rust backend is NOT thread-safe
                from backend.core.memory.manager import Memory
                with Memory._chroma_lock:
                    dense = self._chroma.query(
                        query_embeddings=[query_emb],
                        n_results=top_k * 2,
                        where={"session_id": session_id},
                    )
                if dense and dense.get("metadatas") and dense["metadatas"][0]:
                    for rank, meta in enumerate(dense["metadatas"][0]):
                        dedup_key = str(hash(meta.get("content", "")))
                        results[dedup_key] = results.get(dedup_key, 0) + 1 / (self._k + rank + 1)
            except Exception as e:
                logger.debug(f"ChromaDB dense query failed: {e}")

        # Sparse retrieval via BM25
        if self._bm25 and self._bm25_docs:
            query_tokens = re.findall(r'\w+(?:[.:_]\w+)*', query.lower())
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
                dedup_key = str(hash(content))
                results[dedup_key] = results.get(dedup_key, 0) + 1 / (self._k + bm25_rank + 1)

        # RRF fusion: sort by combined score
        sorted_results = sorted(results.items(), key=lambda x: x[1], reverse=True)

        out = []
        seen = set()
        for dedup_key, _ in sorted_results[:top_k]:
            if dedup_key in seen:
                continue
            seen.add(dedup_key)
            for doc in self._bm25_docs:
                if str(hash(doc.get("content", ""))) == dedup_key:
                    out.append(doc)
                    break
        return out
