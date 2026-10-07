import os
import sqlite3
import time
import json
from typing import List, Dict, Any, Optional
from pydantic import BaseModel, Field
import structlog

from app.rag.config import rag_settings

logger = structlog.get_logger(__name__)


class RetrievalTrace(BaseModel):
    trace_id: str
    query: str
    expanded_query: str
    chunks_retrieved: int
    top_chunk_id: Optional[str] = None
    top_score: float = 0.0
    latency_ms: float = 0.0
    citations: List[str] = Field(default_factory=list)
    domain_breakdown: Dict[str, int] = Field(default_factory=dict)
    timestamp: float = Field(default_factory=time.time)


class RAGTracer:
    """
    Layer 9: Retrieval Observability, Audit Tracing & Latency Metrics.
    Records every retrieval event, scores, citations, and execution latency.
    """

    def __init__(self, db_path: Optional[str] = None):
        if not db_path:
            os.makedirs(rag_settings.RAG_DATA_DIR, exist_ok=True)
            self.db_path = os.path.join(rag_settings.RAG_DATA_DIR, "rag_traces.db")
        else:
            self.db_path = db_path

        self._init_db()

    def _init_db(self):
        try:
            with sqlite3.connect(self.db_path) as conn:
                conn.execute("""
                    CREATE TABLE IF NOT EXISTS rag_traces (
                        trace_id TEXT PRIMARY KEY,
                        query TEXT,
                        expanded_query TEXT,
                        chunks_retrieved INTEGER,
                        top_chunk_id TEXT,
                        top_score REAL,
                        latency_ms REAL,
                        citations_json TEXT,
                        domains_json TEXT,
                        created_at REAL
                    )
                """)
                conn.execute("CREATE INDEX IF NOT EXISTS idx_trace_created ON rag_traces (created_at)")
                conn.commit()
        except Exception as e:
            logger.warning("Could not initialize RAG trace DB", error=str(e))

    def log_trace(self, trace: RetrievalTrace):
        """Record a single retrieval trace asynchronously or synchronously."""
        try:
            with sqlite3.connect(self.db_path) as conn:
                conn.execute("""
                    INSERT OR REPLACE INTO rag_traces (
                        trace_id, query, expanded_query, chunks_retrieved,
                        top_chunk_id, top_score, latency_ms,
                        citations_json, domains_json, created_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    trace.trace_id,
                    trace.query,
                    trace.expanded_query,
                    trace.chunks_retrieved,
                    trace.top_chunk_id,
                    trace.top_score,
                    trace.latency_ms,
                    json.dumps(trace.citations),
                    json.dumps(trace.domain_breakdown),
                    trace.timestamp,
                ))
                conn.commit()
        except Exception as e:
            logger.debug("Failed to record RAG trace", error=str(e))

    def get_recent_traces(self, limit: int = 50) -> List[Dict[str, Any]]:
        """Retrieve latest retrieval traces for UI inspection."""
        try:
            with sqlite3.connect(self.db_path) as conn:
                cur = conn.cursor()
                cur.execute("""
                    SELECT trace_id, query, expanded_query, chunks_retrieved,
                           top_chunk_id, top_score, latency_ms, citations_json,
                           domains_json, created_at
                    FROM rag_traces ORDER BY created_at DESC LIMIT ?
                """, (limit,))
                rows = cur.fetchall()
                return [
                    {
                        "trace_id": r[0],
                        "query": r[1],
                        "expanded_query": r[2],
                        "chunks_retrieved": r[3],
                        "top_chunk_id": r[4],
                        "top_score": round(r[5], 4),
                        "latency_ms": round(r[6], 2),
                        "citations": json.loads(r[7]) if r[7] else [],
                        "domains": json.loads(r[8]) if r[8] else {},
                        "created_at": r[9],
                    }
                    for r in rows
                ]
        except Exception as e:
            logger.error("Failed to query RAG traces", error=str(e))
            return []

    def get_metrics(self) -> Dict[str, Any]:
        """Aggregate SLO and performance metrics."""
        try:
            with sqlite3.connect(self.db_path) as conn:
                cur = conn.cursor()
                cur.execute("SELECT COUNT(*), AVG(latency_ms), AVG(chunks_retrieved) FROM rag_traces")
                total, avg_lat, avg_chunks = cur.fetchone()

                cur.execute("SELECT COUNT(*) FROM rag_traces WHERE chunks_retrieved = 0")
                zero_hits = cur.fetchone()[0]

                zero_hit_rate = (zero_hits / total) if total and total > 0 else 0.0

                return {
                    "total_retrieval_queries": total or 0,
                    "avg_latency_ms": round(avg_lat or 0.0, 2),
                    "avg_chunks_per_query": round(avg_chunks or 0.0, 2),
                    "zero_hit_rate_pct": round(zero_hit_rate * 100, 2),
                }
        except Exception as e:
            logger.error("Failed to calculate RAG metrics", error=str(e))
            return {
                "total_retrieval_queries": 0,
                "avg_latency_ms": 0.0,
                "avg_chunks_per_query": 0.0,
                "zero_hit_rate_pct": 0.0,
            }


rag_tracer = RAGTracer()
