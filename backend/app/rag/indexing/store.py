import os
import json
import math
import sqlite3
import re
from typing import List, Dict, Any, Optional, Tuple
import structlog

from app.rag.models import Chunk, SearchResult
from app.rag.config import rag_settings

logger = structlog.get_logger(__name__)


class HybridVectorStore:
    """
    Hybrid Index Store combining Dense Vectors + Sparse BM25 index.
    Features:
    - Namespace/domain isolation (terraform_aws, cis_benchmarks, past_plans, remediations)
    - Metadata payload indexing
    - Persistent SQLite storage
    - Cosine similarity computation
    - BM25 Okapi term scoring
    """

    def __init__(self, db_path: Optional[str] = None):
        if not db_path:
            os.makedirs(rag_settings.RAG_DATA_DIR, exist_ok=True)
            self.db_path = os.path.join(rag_settings.RAG_DATA_DIR, "hybrid_rag_store.db")
        else:
            self.db_path = db_path

        self._init_db()

    def _init_db(self):
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS rag_chunks (
                    chunk_id TEXT PRIMARY KEY,
                    doc_id TEXT,
                    domain TEXT,
                    title TEXT,
                    content TEXT,
                    hcl_code TEXT,
                    resource_type TEXT,
                    provider TEXT,
                    version TEXT,
                    metadata_json TEXT,
                    content_hash TEXT,
                    token_estimate INTEGER,
                    vector_csv TEXT
                )
            """)
            conn.execute("CREATE INDEX IF NOT EXISTS idx_rag_domain ON rag_chunks (domain)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_rag_resource ON rag_chunks (resource_type)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_rag_hash ON rag_chunks (content_hash)")

            # BM25 statistics table
            conn.execute("""
                CREATE TABLE IF NOT EXISTS bm25_terms (
                    term TEXT,
                    chunk_id TEXT,
                    term_freq INTEGER,
                    PRIMARY KEY (term, chunk_id)
                )
            """)
            conn.execute("CREATE INDEX IF NOT EXISTS idx_bm25_term ON bm25_terms (term)")
            conn.commit()

    @staticmethod
    def tokenize(text: str) -> List[str]:
        """Extract lowercase alphanumeric tokens, preserving snake_case words intact."""
        clean = text.lower()
        # Keep both full snake_case tokens and sub-tokens
        tokens = re.findall(r'[a-z0-9_]+', clean)
        sub_tokens = []
        for t in tokens:
            if "_" in t:
                sub_tokens.extend(t.split("_"))
        return tokens + sub_tokens

    def add_chunks(self, chunks: List[Chunk], vectors: List[List[float]]) -> int:
        """Store chunks and their embedding vectors + BM25 inverted index."""
        if not chunks:
            return 0

        inserted = 0
        with sqlite3.connect(self.db_path) as conn:
            cur = conn.cursor()
            for chunk, vec in zip(chunks, vectors):
                vec_csv = ",".join(f"{x:.6f}" for x in vec) if vec else ""
                cur.execute("""
                    INSERT OR REPLACE INTO rag_chunks (
                        chunk_id, doc_id, domain, title, content, hcl_code,
                        resource_type, provider, version, metadata_json, content_hash,
                        token_estimate, vector_csv
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    chunk.chunk_id,
                    chunk.doc_id,
                    chunk.domain,
                    chunk.title,
                    chunk.content,
                    chunk.hcl_code,
                    chunk.resource_type,
                    chunk.provider,
                    chunk.version,
                    json.dumps(chunk.metadata),
                    chunk.content_hash,
                    chunk.token_estimate,
                    vec_csv,
                ))

                # Index terms for BM25
                tokens = self.tokenize(f"{chunk.title} {chunk.content} {chunk.resource_type or ''}")
                term_counts: Dict[str, int] = {}
                for t in tokens:
                    term_counts[t] = term_counts.get(t, 0) + 1

                for term, freq in term_counts.items():
                    cur.execute(
                        "INSERT OR REPLACE INTO bm25_terms (term, chunk_id, term_freq) VALUES (?, ?, ?)",
                        (term, chunk.chunk_id, freq),
                    )
                inserted += 1

            conn.commit()

        logger.info("Indexed chunks into hybrid store", count=inserted)
        return inserted

    def dense_search(
        self,
        query_vector: List[float],
        top_k: int = 15,
        domain: Optional[str] = None,
        resource_type: Optional[str] = None,
    ) -> List[Tuple[Chunk, float]]:
        """Dense similarity search using dot product on normalized vectors (cosine)."""
        candidates = []
        with sqlite3.connect(self.db_path) as conn:
            cur = conn.cursor()
            query = "SELECT chunk_id, doc_id, domain, title, content, hcl_code, resource_type, provider, version, metadata_json, token_estimate, vector_csv FROM rag_chunks"
            params: List[Any] = []
            conditions = []

            if domain:
                conditions.append("domain = ?")
                params.append(domain)
            if resource_type:
                conditions.append("resource_type = ?")
                params.append(resource_type)

            if conditions:
                query += " WHERE " + " AND ".join(conditions)

            cur.execute(query, params)
            rows = cur.fetchall()

            for r in rows:
                if not r[11]:  # vector_csv
                    continue
                v = [float(x) for x in r[11].split(",")]
                # Cosine similarity on unit vectors is simply dot product
                sim = sum(a * b for a, b in zip(query_vector, v))

                metadata = json.loads(r[9]) if r[9] else {}
                chunk = Chunk(
                    chunk_id=r[0],
                    doc_id=r[1],
                    domain=r[2],
                    title=r[3],
                    content=r[4],
                    hcl_code=r[5],
                    resource_type=r[6],
                    provider=r[7],
                    version=r[8],
                    metadata=metadata,
                    token_estimate=r[10],
                )
                candidates.append((chunk, sim))

        candidates.sort(key=lambda x: x[1], reverse=True)
        return candidates[:top_k]

    def sparse_search(
        self,
        query_text: str,
        top_k: int = 15,
        domain: Optional[str] = None,
        k1: float = 1.2,
        b: float = 0.75,
    ) -> List[Tuple[Chunk, float]]:
        """
        Sparse BM25 Okapi search for exact token matching (e.g. aws_db_subnet_group).
        """
        tokens = self.tokenize(query_text)
        if not tokens:
            return []

        with sqlite3.connect(self.db_path) as conn:
            cur = conn.cursor()

            # Get total document count N
            cur.execute("SELECT COUNT(*) FROM rag_chunks" + (f" WHERE domain = '{domain}'" if domain else ""))
            total_docs = cur.fetchone()[0]
            if total_docs == 0:
                return []

            # Get average document length
            cur.execute("SELECT AVG(token_estimate) FROM rag_chunks")
            avg_dl = cur.fetchone()[0] or 100.0

            scores: Dict[str, float] = {}

            for term in set(tokens):
                # Document frequency df for this term
                cur.execute("""
                    SELECT COUNT(DISTINCT b.chunk_id) 
                    FROM bm25_terms b 
                    JOIN rag_chunks c ON b.chunk_id = c.chunk_id
                    WHERE b.term = ?
                """ + (f" AND c.domain = '{domain}'" if domain else ""), (term,))
                df = cur.fetchone()[0]
                if df == 0:
                    continue

                # IDF calculation with smoothing
                idf = math.log(1.0 + (total_docs - df + 0.5) / (df + 0.5))

                # Term frequencies for each matching chunk
                cur.execute("""
                    SELECT b.chunk_id, b.term_freq, c.token_estimate
                    FROM bm25_terms b
                    JOIN rag_chunks c ON b.chunk_id = c.chunk_id
                    WHERE b.term = ?
                """ + (f" AND c.domain = '{domain}'" if domain else ""), (term,))

                for cid, tf, dl in cur.fetchall():
                    denom = tf + k1 * (1.0 - b + b * (dl / avg_dl))
                    term_score = idf * (tf * (k1 + 1.0) / denom)
                    scores[cid] = scores.get(cid, 0.0) + term_score

            if not scores:
                return []

            # Fetch top-k chunks
            sorted_cids = sorted(scores.items(), key=lambda x: x[1], reverse=True)[:top_k]
            results: List[Tuple[Chunk, float]] = []

            for cid, score in sorted_cids:
                cur.execute("""
                    SELECT chunk_id, doc_id, domain, title, content, hcl_code,
                           resource_type, provider, version, metadata_json, token_estimate
                    FROM rag_chunks WHERE chunk_id = ?
                """, (cid,))
                r = cur.fetchone()
                if r:
                    metadata = json.loads(r[9]) if r[9] else {}
                    chunk = Chunk(
                        chunk_id=r[0],
                        doc_id=r[1],
                        domain=r[2],
                        title=r[3],
                        content=r[4],
                        hcl_code=r[5],
                        resource_type=r[6],
                        provider=r[7],
                        version=r[8],
                        metadata=metadata,
                        token_estimate=r[10],
                    )
                    results.append((chunk, score))

            return results

    def count_chunks(self) -> int:
        with sqlite3.connect(self.db_path) as conn:
            cur = conn.cursor()
            cur.execute("SELECT COUNT(*) FROM rag_chunks")
            return cur.fetchone()[0]
