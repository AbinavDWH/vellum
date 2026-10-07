import os
import time
import uuid
from typing import Dict, Any, List, Optional
import structlog

from app.rag.config import rag_settings
from app.rag.models import SearchResult, GroundedContext
from app.rag.ingestion.chunker import CodeAwareChunker
from app.rag.ingestion.pipeline import IngestionPipeline
from app.rag.indexing.embeddings import EmbeddingEngine
from app.rag.indexing.store import HybridVectorStore
from app.rag.retrieval.hybrid import HybridRetriever
from app.rag.query.expander import QueryExpander, ParsedQuery
from app.rag.observability.tracer import rag_tracer, RetrievalTrace
from app.rag.eval.benchmark import GoldenBenchmarkRunner, BenchmarkResult

logger = structlog.get_logger(__name__)


class RAGService:
    """
    Central orchestration service for Vellum's 11-Layer Production RAG subsystem.
    Manages:
    - Layer 1 & 2: Ingestion & Code-Aware Chunking
    - Layer 3: Normalized Embedding Engine + Persistent Cache
    - Layer 4: Hybrid Dense + Sparse BM25 Vector Store
    - Layer 5: Query Understanding & Acronym Expansion
    - Layer 6 & 7: Hybrid RRF Retrieval, Attribute Reranking, Citation Grounding
    - Layer 8: Golden Dataset Quantitative Benchmark
    - Layer 9: Observability Tracing & Latency Metrics
    """

    def __init__(self, knowledge_dir: Optional[str] = None):
        self.knowledge_dir = knowledge_dir or os.path.join(
            os.path.dirname(__file__), "knowledge"
        )
        self.chunker = CodeAwareChunker()
        self.pipeline = IngestionPipeline(chunker=self.chunker)
        self.embeddings = EmbeddingEngine()
        self.store = HybridVectorStore()
        self.retriever = HybridRetriever(
            store=self.store,
            embedding_engine=self.embeddings,
            rrf_k=rag_settings.RRF_K,
            min_threshold=rag_settings.MIN_SCORE_THRESHOLD,
        )
        self.expander = QueryExpander()
        self.tracer = rag_tracer
        self.eval_runner = GoldenBenchmarkRunner(rag_service=self)

    def ingest_knowledge_base(self, force_reindex: bool = False) -> Dict[str, Any]:
        """
        Scan and index all curated markdown knowledge documents across domains.
        """
        start_time = time.time()
        logger.info("Starting knowledge base ingestion", knowledge_dir=self.knowledge_dir)

        if not os.path.exists(self.knowledge_dir):
            logger.warning("Knowledge directory not found", path=self.knowledge_dir)
            return {"status": "error", "message": f"Knowledge directory {self.knowledge_dir} not found"}

        domain_folders = [
            f for f in os.listdir(self.knowledge_dir)
            if os.path.isdir(os.path.join(self.knowledge_dir, f))
        ]

        total_docs = 0
        total_chunks_created = 0
        domain_counts: Dict[str, int] = {}

        for domain in domain_folders:
            domain_path = os.path.join(self.knowledge_dir, domain)
            docs, chunks = self.pipeline.ingest_directory(
                directory=domain_path,
                domain=domain,
                provider="aws",
                version="5.0",
            )
            total_docs += len(docs)
            domain_counts[domain] = len(chunks)

            if chunks:
                texts_to_embed = [
                    f"{c.title} {c.resource_type or ''}: {c.content}"
                    for c in chunks
                ]
                vectors = self.embeddings.embed_batch(texts_to_embed)
                inserted = self.store.add_chunks(chunks, vectors)
                total_chunks_created += inserted

        elapsed = time.time() - start_time
        current_total = self.store.count_chunks()

        stats = {
            "status": "success",
            "documents_scanned": total_docs,
            "chunks_indexed": total_chunks_created,
            "total_chunks_in_store": current_total,
            "domains": domain_counts,
            "time_elapsed_seconds": round(elapsed, 3),
        }
        logger.info("Knowledge base ingestion completed", **stats)
        return stats

    def get_stats(self) -> Dict[str, Any]:
        """Return operational statistics about the vector store."""
        return {
            "total_chunks": self.store.count_chunks(),
            "embedding_model": self.embeddings.model_name,
            "embedding_dim": self.embeddings.dimension,
            "knowledge_dir": self.knowledge_dir,
            "metrics": self.tracer.get_metrics(),
        }

    def search(
        self,
        query: str,
        top_k: int = rag_settings.TOP_K_RERANKED,
        domain: Optional[str] = None,
        resource_type: Optional[str] = None,
        enable_expansion: bool = True,
    ) -> List[SearchResult]:
        """
        Execute hybrid search with Layer 5 query expansion and Layer 9 observability tracing.
        """
        t0 = time.time()
        parsed: Optional[ParsedQuery] = None

        search_query = query
        target_domain = domain
        target_resource = resource_type

        if enable_expansion:
            parsed = self.expander.expand(query)
            search_query = parsed.expanded_query
            # Allow semantic boost rather than hard WHERE filter for resource types
            if not target_domain and parsed.target_domain and parsed.target_domain == "cis_benchmarks":
                target_domain = parsed.target_domain

        # Multi-query handling for compound requests
        if parsed and len(parsed.sub_queries) > 1:
            candidates: Dict[str, SearchResult] = {}
            for sub_q in parsed.sub_queries:
                sub_hits = self.retriever.search(
                    query=sub_q,
                    top_k=top_k,
                    domain=target_domain,
                )
                for h in sub_hits:
                    if h.chunk_id not in candidates or h.final_score > candidates[h.chunk_id].final_score:
                        candidates[h.chunk_id] = h

            sorted_results = sorted(candidates.values(), key=lambda x: x.final_score, reverse=True)[:top_k]
            # Reassign citation tags
            for idx, r in enumerate(sorted_results, start=1):
                r.citation_tag = f"[DOC-{idx}]"
            results = sorted_results
        else:
            results = self.retriever.search(
                query=search_query,
                top_k=top_k,
                domain=target_domain,
                resource_type=target_resource,
            )

        latency_ms = (time.time() - t0) * 1000

        # Layer 9: Log trace
        domain_counts: Dict[str, int] = {}
        for r in results:
            domain_counts[r.domain] = domain_counts.get(r.domain, 0) + 1

        trace = RetrievalTrace(
            trace_id=f"tr_{uuid.uuid4().hex[:10]}",
            query=query,
            expanded_query=search_query,
            chunks_retrieved=len(results),
            top_chunk_id=results[0].chunk_id if results else None,
            top_score=results[0].final_score if results else 0.0,
            latency_ms=latency_ms,
            citations=[f"{r.citation_tag} {r.title}" for r in results],
            domain_breakdown=domain_counts,
        )
        self.tracer.log_trace(trace)

        return results

    def assemble_grounded_context(
        self,
        query: str,
        top_k: int = rag_settings.TOP_K_RERANKED,
        max_tokens: int = rag_settings.MAX_CONTEXT_TOKENS,
    ) -> GroundedContext:
        """Assemble citation-tagged context for LLM prompt grounding."""
        results = self.search(query, top_k=top_k)

        if not results:
            return GroundedContext(
                formatted_context="INSUFFICIENT_CONTEXT: No authoritative infrastructure documentation found matching query.",
                citations=[],
                total_tokens_estimate=0,
                has_sufficient_context=False,
                domain_breakdown={},
            )

        context_blocks = []
        token_count = 0
        accepted_citations: List[SearchResult] = []
        domain_counts: Dict[str, int] = {}

        for item in results:
            block = (
                f"{item.citation_tag} Reference: {item.title} ({item.domain})\n"
                f"Resource Type: {item.resource_type or 'General'}\n"
                f"Content:\n{item.content.strip()}\n"
            )
            est_tokens = len(block) // 4

            if token_count + est_tokens > max_tokens and accepted_citations:
                break

            context_blocks.append(block)
            token_count += est_tokens
            accepted_citations.append(item)
            domain_counts[item.domain] = domain_counts.get(item.domain, 0) + 1

        formatted = "\n---\n".join(context_blocks)
        return GroundedContext(
            formatted_context=formatted,
            citations=accepted_citations,
            total_tokens_estimate=token_count,
            has_sufficient_context=True,
            domain_breakdown=domain_counts,
        )

    def run_benchmark(self, top_k: int = 5) -> BenchmarkResult:
        """Layer 8: Execute Golden Dataset evaluation suite."""
        return self.eval_runner.run_eval(top_k=top_k)

    def get_traces(self, limit: int = 50) -> List[Dict[str, Any]]:
        """Layer 9: Return recent observability traces."""
        return self.tracer.get_recent_traces(limit=limit)


# Global singleton instance
_rag_service: Optional[RAGService] = None


def get_rag_service() -> RAGService:
    global _rag_service
    if _rag_service is None:
        _rag_service = RAGService()
    return _rag_service
