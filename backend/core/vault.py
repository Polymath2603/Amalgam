"""
Standalone vault manager.
Reads/writes markdown files in the vault directory and provides
search functionality independent of any MCP server.
"""
import re
import logging
import hashlib
from pathlib import Path
from typing import List, Dict, Optional, Callable

try:
    import chromadb
    from chromadb.config import Settings as ChromaSettings
    _HAS_CHROMADB = True
except ImportError:
    _HAS_CHROMADB = False
from rank_bm25 import BM25Okapi

logger = logging.getLogger(__name__)

# Increased from 500 to 1000 chars (~250-500 tokens) for better embedding context
VAULT_CHUNK_SIZE = 1000


class VaultManager:
    def __init__(self, vault_path: str, embeddings_path: str = None):
        self._vault_path = Path(vault_path)
        self._chroma = None
        self._chroma_col = None
        self._index_mtime: Dict[str, float] = {}
        self._bm25 = None
        self._bm25_docs: List[Dict] = []
        self._bm25_mtimes: Dict[str, float] = {}
        if embeddings_path and _HAS_CHROMADB:
            ep = Path(embeddings_path)
            ep.mkdir(parents=True, exist_ok=True)
            self._chroma = chromadb.PersistentClient(
                path=str(ep),
                settings=ChromaSettings(anonymized_telemetry=False),
            )
            self._chroma_col = self._chroma.get_or_create_collection(
                name="vault",
                metadata={"hnsw:space": "cosine"},
            )

    @property
    def vault_path(self) -> Path:
        return self._vault_path

    def list_files(self) -> List[Dict]:
        """List all files in the vault directory with metadata."""
        if not self._vault_path.exists():
            return []
        files = []
        for f in sorted(self._vault_path.rglob("*")):
            if f.is_file():
                rel = str(f.relative_to(self._vault_path))
                files.append({
                    "name": rel,
                    "size": f.stat().st_size,
                    "modified": f.stat().st_mtime,
                })
        return files

    def _safe_path(self, filename: str) -> Optional[Path]:
        path = (self._vault_path / filename).resolve()
        vault_resolved = self._vault_path.resolve()
        if vault_resolved not in path.parents and path != vault_resolved:
            logger.warning(f"Path traversal blocked: {filename}")
            return None
        return path

    def read(self, filename: str) -> Optional[str]:
        path = self._safe_path(filename)
        if not path or not path.exists() or not path.is_file():
            return None
        try:
            return path.read_bytes().decode("utf-8")
        except Exception as e:
            logger.error(f"Failed to read vault file {filename}: {e}")
            return None

    def write(self, filename: str, content: str) -> bool:
        path = self._safe_path(filename)
        if not path:
            return False
        self._vault_path.mkdir(parents=True, exist_ok=True)
        try:
            path.write_bytes(content.encode("utf-8"))
            return True
        except Exception as e:
            logger.error(f"Failed to write vault file {filename}: {e}")
            return False

    def delete(self, filename: str) -> bool:
        path = self._safe_path(filename)
        if not path or not path.exists():
            return False
        try:
            path.unlink()
            return True
        except Exception as e:
            logger.error(f"Failed to delete vault file {filename}: {e}")
            return False

    def _build_bm25_index(self):
        """Build or rebuild the BM25 index from vault files. Cached with mtime invalidation."""
        self._vault_path.mkdir(parents=True, exist_ok=True)
        if not self._vault_path.exists():
            self._bm25 = None
            self._bm25_docs = []
            self._bm25_mtimes = {}
            return

        current_mtimes = {}
        for f in self._vault_path.rglob("*.md"):
            if f.is_file():
                current_mtimes[str(f.relative_to(self._vault_path))] = f.stat().st_mtime

        # _bm25 is always initialized in __init__, so hasattr check is unnecessary
        if current_mtimes == self._bm25_mtimes and self._bm25 is not None:
            return

        self._bm25_docs = []
        tokenized_corpus = []
        for rel_path, mtime in current_mtimes.items():
            try:
                content = (self._vault_path / rel_path).read_text(encoding="utf-8")
            except Exception:
                continue
            tokens = content.lower().split()
            self._bm25_docs.append({"path": rel_path, "content": content})
            tokenized_corpus.append(tokens)

        if tokenized_corpus:
            self._bm25 = BM25Okapi(tokenized_corpus)
        else:
            self._bm25 = None
        self._bm25_mtimes = current_mtimes

    def search(self, query: str, max_results: int = 5) -> List[Dict]:
        """BM25 search across all markdown files in the vault."""
        self._build_bm25_index()
        if not self._bm25 or not self._bm25_docs:
            return []

        query_tokens = query.lower().split()
        scores = self._bm25.get_scores(query_tokens)

        ranked = sorted(enumerate(scores), key=lambda x: x[1], reverse=True)
        results = []
        for idx, score in ranked[:max_results]:
            doc = self._bm25_docs[idx]
            content = doc["content"]

            snippet = ""
            query_lower = query.lower()
            for word in query_lower.split():
                ci = content.lower().find(word)
                if ci != -1:
                    start = max(0, ci - 60)
                    end = min(len(content), ci + len(word) + 60)
                    snippet = content[start:end].strip()
                    if start > 0:
                        snippet = "..." + snippet
                    if end < len(content):
                        snippet = snippet + "..."
                    break

            results.append({
                "filename": doc["path"],
                "score": round(float(score), 1),
                "snippet": snippet or content[:200],
                "size": len(content.encode("utf-8")),
            })

        return results

    def tag_search(self, tag: str, max_results: int = 10) -> List[Dict]:
        """Search for files containing a specific tag."""
        if not self._vault_path.exists():
            return []
        pattern = re.compile(rf'#\s*{re.escape(tag)}\b', re.IGNORECASE)
        results = []
        for f in self._vault_path.rglob("*.md"):
            if not f.is_file():
                continue
            try:
                content = f.read_text(encoding="utf-8")
            except Exception:
                continue
            matches = pattern.findall(content)
            if matches:
                results.append({
                    "filename": f.name,
                    "tag": tag,
                    "match_count": len(matches),
                })
        return results[:max_results]

    def _chunk_text(self, text: str, chunk_size: int = VAULT_CHUNK_SIZE) -> List[str]:
        """Split text into chunks of roughly chunk_size characters, breaking at paragraph/sentence boundaries."""
        if len(text) <= chunk_size:
            return [text]
        chunks = []
        start = 0
        while start < len(text):
            end = start + chunk_size
            if end >= len(text):
                chunks.append(text[start:])
                break

            para_break = text.rfind("\n\n", start, end)
            if para_break > start + chunk_size // 3:
                end = para_break + 2
            else:
                for delim in (". ", "! ", "? ", "\n"):
                    sent_break = text.rfind(delim, start, end)
                    if sent_break > start + chunk_size // 3:
                        end = sent_break + len(delim)
                        break
            chunks.append(text[start:end])
            start = end
        return chunks

    async def _index_vault(self, get_embedding_fn: Callable):
        """Index all .md vault files into ChromaDB. Re-index only changed files."""
        if not self._chroma_col or not self._vault_path.exists() or not get_embedding_fn:
            return

        # Use rglob to include subdirectory files (consistent with _build_bm25_index)
        current_files = {}
        for f in self._vault_path.rglob("*.md"):
            if f.is_file():
                # Use relative path as key for consistency
                rel = str(f.relative_to(self._vault_path))
                current_files[rel] = f

        to_index = []
        for name, f in current_files.items():
            mtime = f.stat().st_mtime
            if name not in self._index_mtime or self._index_mtime[name] != mtime:
                to_index.append((name, f, mtime))

        indexed_names = set(self._index_mtime.keys())
        current_names = set(current_files.keys())
        deleted = indexed_names - current_names
        for name in deleted:
            try:
                self._chroma_col.delete(where={"filename": name})
            except Exception as e:
                logger.warning(f"Failed to delete stale ChromaDB entry for {name}: {e}")
            del self._index_mtime[name]

        if not to_index:
            return

        for name, f, mtime in to_index:
            try:
                content = f.read_text(encoding="utf-8")
            except Exception:
                continue

            try:
                self._chroma_col.delete(where={"filename": name})
            except Exception as e:
                logger.warning(f"Failed to delete old embeddings for {name}: {e}")

            chunks = self._chunk_text(content)
            ids, embeddings, metadatas = [], [], []
            for i, chunk in enumerate(chunks):
                emb = await get_embedding_fn(chunk)
                if not emb:
                    continue
                cid = f"{name}_chunk_{i}"
                ids.append(cid)
                embeddings.append(emb)
                metadatas.append({
                    "filename": name,
                    "chunk_index": i,
                    "content": chunk,
                    "mtime": mtime,
                })

            if ids:
                try:
                    self._chroma_col.upsert(ids=ids, embeddings=embeddings, metadatas=metadatas)
                    self._index_mtime[name] = mtime
                except Exception as e:
                    logger.warning(f"Vault ChromaDB index failed for {name}: {e}")

    async def semantic_search(self, query: str, get_embedding_fn: Callable, top_k: int = 5) -> List[Dict]:
        """Semantic search across vault files using ChromaDB embeddings.

        Args:
            query: Search query text
            get_embedding_fn: async callable(text) -> List[float] for embedding
            top_k: Maximum results to return

        Returns:
            List of dicts with filename, snippet, distance, chunk_index
        """
        if not self._chroma_col or not get_embedding_fn:
            return []

        await self._index_vault(get_embedding_fn)

        query_emb = await get_embedding_fn(query)
        if not query_emb:
            return []

        try:
            results = self._chroma_col.query(
                query_embeddings=[query_emb],
                n_results=min(top_k, self._chroma_col.count() or 1),
            )
            if not results or not results["metadatas"] or not results["metadatas"][0]:
                return []

            distances = results["distances"][0] if results.get("distances") else [None] * len(results["metadatas"][0])
            return [
                {
                    "filename": m.get("filename", ""),
                    "snippet": m.get("content", "")[:200],
                    "chunk_index": m.get("chunk_index", 0),
                    "distance": d,
                }
                for m, d in zip(results["metadatas"][0], distances)
            ]
        except Exception as e:
            logger.warning(f"Vault ChromaDB query failed: {e}")
            return []

    def inject_to_context(self, max_tokens: int = 2000) -> str:
        """Read all .md files up to max_tokens and return formatted context string.

        Returns empty string if no vault files or vault_path doesn't exist.
        """
        from backend.core.utils.tokens import estimate_tokens, truncate_to_token_limit

        if not self._vault_path.exists():
            return ""

        sections = []
        token_usage = 0

        for f in sorted(self._vault_path.rglob("*.md")):
            if not f.is_file():
                continue
            try:
                content = f.read_text(encoding="utf-8").strip()
            except Exception:
                continue
            if not content:
                continue

            # Estimate token count of this file's content
            file_tokens = estimate_tokens(content)
            if token_usage + file_tokens > max_tokens:
                # Truncate this file to fit remaining budget
                remaining = max_tokens - token_usage
                if remaining > 0:
                    content = truncate_to_token_limit(content, remaining)
                else:
                    break

            section_name = f.stem.replace("_", " ").title()
            sections.append(f"\n\n### {section_name}\n{content}")
            token_usage += estimate_tokens(content)

        if sections:
            result = "".join(sections)
            logger.debug(f"Injected {len(sections)} vault file(s) ({token_usage} tokens)")
            return result
        return ""
