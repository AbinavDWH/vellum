import math
import hashlib
import sqlite3
import os
from typing import List, Dict, Optional
import httpx
import structlog

from app.rag.config import rag_settings

logger = structlog.get_logger(__name__)


class EmbeddingEngine:
    """
    Embedding engine interfacing with LM Studio (text-embedding-nomic-embed-text-v1.5),
    with persistent SQLite caching, vector normalization, and deterministic fallback.
    """

    def __init__(
        self,
        endpoint_url: str = rag_settings.LM_STUDIO_EMBEDDINGS_URL,
        model_name: str = rag_settings.EMBEDDING_MODEL,
        dimension: int = rag_settings.EMBEDDING_DIMENSION,
        cache_db_path: Optional[str] = None,
    ):
        self.endpoint_url = endpoint_url
        self.model_name = model_name
        self.dimension = dimension
        self.timeout = rag_settings.EMBEDDING_TIMEOUT

        # Set up SQLite persistent cache
        if not cache_db_path:
            os.makedirs(rag_settings.RAG_DATA_DIR, exist_ok=True)
            self.cache_db_path = os.path.join(rag_settings.RAG_DATA_DIR, "embeddings_cache.db")
        else:
            self.cache_db_path = cache_db_path

        self._init_cache_db()
        self.in_memory_cache: Dict[str, List[float]] = {}

    def _init_cache_db(self):
        try:
            with sqlite3.connect(self.cache_db_path) as conn:
                conn.execute("""
                    CREATE TABLE IF NOT EXISTS embedding_cache (
                        text_hash TEXT PRIMARY KEY,
                        model_name TEXT,
                        vector_csv TEXT
                    )
                """)
                conn.commit()
        except Exception as e:
            logger.warning("Could not initialize embedding cache DB", error=str(e))

    @staticmethod
    def normalize(vector: List[float]) -> List[float]:
        """Apply L2 normalization to ensure unit length for exact cosine similarity."""
        norm = math.sqrt(sum(x * x for x in vector))
        if norm == 0:
            return vector
        return [x / norm for x in vector]

    def _get_cached_embedding(self, text_hash: str) -> Optional[List[float]]:
        if text_hash in self.in_memory_cache:
            return self.in_memory_cache[text_hash]

        try:
            with sqlite3.connect(self.cache_db_path) as conn:
                cur = conn.cursor()
                cur.execute(
                    "SELECT vector_csv FROM embedding_cache WHERE text_hash = ? AND model_name = ?",
                    (text_hash, self.model_name),
                )
                row = cur.fetchone()
                if row:
                    vec = [float(x) for x in row[0].split(",")]
                    self.in_memory_cache[text_hash] = vec
                    return vec
        except Exception:
            pass
        return None

    def _save_cached_embedding(self, text_hash: str, vector: List[float]):
        self.in_memory_cache[text_hash] = vector
        try:
            with sqlite3.connect(self.cache_db_path) as conn:
                csv_data = ",".join(f"{x:.6f}" for x in vector)
                conn.execute(
                    "INSERT OR REPLACE INTO embedding_cache (text_hash, model_name, vector_csv) VALUES (?, ?, ?)",
                    (text_hash, self.model_name, csv_data),
                )
                conn.commit()
        except Exception as e:
            logger.debug("Failed to write to embedding cache", error=str(e))

    def embed_text(self, text: str) -> List[float]:
        """Embed a single text string."""
        results = self.embed_batch([text])
        return results[0]

    def embed_batch(self, texts: List[str]) -> List[List[float]]:
        """Embed a batch of texts, leveraging cache and LM Studio."""
        results: List[Optional[List[float]]] = [None] * len(texts)
        texts_to_fetch_idx: List[int] = []

        # 1. Check cache
        for i, text in enumerate(texts):
            clean = text.strip()
            thash = hashlib.sha256(clean.encode("utf-8")).hexdigest()
            cached = self._get_cached_embedding(thash)
            if cached is not None:
                results[i] = cached
            else:
                texts_to_fetch_idx.append(i)

        if not texts_to_fetch_idx:
            return [r for r in results if r is not None]

        # 2. Call LM Studio API for missing texts (or fast deterministic vectors in groq mode)
        missing_texts = [texts[idx].strip() for idx in texts_to_fetch_idx]
        fetched_vectors: List[List[float]] = []

        from app.config import settings
        if (settings.LLM_PROVIDER or "").lower() == "groq":
            fetched_vectors = [self._deterministic_hash_vector(t) for t in missing_texts]
        else:
            try:
                with httpx.Client(timeout=self.timeout) as client:
                    res = client.post(
                        self.endpoint_url,
                        json={
                            "model": self.model_name,
                            "input": missing_texts if len(missing_texts) > 1 else missing_texts[0],
                        },
                    )
                    if res.status_code == 200:
                        data = res.json().get("data", [])
                        data_sorted = sorted(data, key=lambda x: x.get("index", 0))
                        for item in data_sorted:
                            vec = item.get("embedding", [])
                            norm_vec = self.normalize(vec)
                            fetched_vectors.append(norm_vec)
                    else:
                        logger.warning("LM Studio embeddings non-200, falling back", status=res.status_code)
                        fetched_vectors = [self._deterministic_hash_vector(t) for t in missing_texts]
            except Exception as e:
                logger.warning("LM Studio embeddings failed or offline, using fallback", error=str(e))
                fetched_vectors = [self._deterministic_hash_vector(t) for t in missing_texts]

        # 3. Cache and assign results
        for idx, vec in zip(texts_to_fetch_idx, fetched_vectors):
            thash = hashlib.sha256(texts[idx].strip().encode("utf-8")).hexdigest()
            self._save_cached_embedding(thash, vec)
            results[idx] = vec

        return [r for r in results if r is not None]

    def _deterministic_hash_vector(self, text: str) -> List[float]:
        """
        Deterministic pseudo-dense projection (fallback when LM Studio is offline).
        Maintains consistent dimensions (768) and cosine normalization.
        """
        vec = [0.0] * self.dimension
        words = text.lower().split()
        for w in words:
            h = int(hashlib.md5(w.encode("utf-8")).hexdigest(), 16)
            idx = h % self.dimension
            sign = 1.0 if ((h >> 4) & 1) == 1 else -1.0
            vec[idx] += sign

        return self.normalize(vec)
