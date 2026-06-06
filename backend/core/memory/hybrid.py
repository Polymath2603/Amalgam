try:
    from rank_bm25 import BM25Okapi
except ImportError:
    BM25Okapi = None
import re
from typing import Any


class HybridRetrieval:
    def __init__(self, chroma_col, k: int = 60):
        self._chroma = chroma_col
        self._k = k
        self._bm25: BM25Okapi | None = None
        self._bm25_docs: list[dict] = []

    def rebuild_bm25(self, messages: list[dict]):
        corpus = []
        self._bm25_docs = messages
        for msg in messages:
            tokens = re.findall(r'\b\w+\b', msg.get('content', '').lower())
            corpus.append(tokens)
        self._bm25 = BM25Okapi(corpus) if corpus else None

    async def retrieve(self, query: str, query_emb: list[float],
                       session_id: str, top_k: int = 5) -> list[dict]:
        results: dict[str, float] = {}

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
        except Exception:
            pass

        if self._bm25 and self._bm25_docs:
            query_tokens = re.findall(r'\b\w+\b', query.lower())
            scores = self._bm25.get_scores(query_tokens)
            ranked = sorted(enumerate(scores), key=lambda x: x[1], reverse=True)
            for rank, (idx, score) in enumerate(ranked[:top_k * 2]):
                if score > 0 and idx < len(self._bm25_docs):
                    cid = self._bm25_docs[idx].get("content", "")[:50]
                    results[cid] = results.get(cid, 0) + 1 / (self._k + rank + 1)

        sorted_results = sorted(results.items(), key=lambda x: x[1], reverse=True)

        out = []
        for cid, _ in sorted_results[:top_k]:
            for doc in self._bm25_docs:
                if doc.get("content", "")[:50] == cid:
                    out.append(doc)
                    break
        return out
