from typing import List, Dict, Any, Optional
import structlog

from app.rag.models import SearchResult, Chunk, GroundedContext
from app.rag.config import rag_settings
from app.rag.indexing.embeddings import EmbeddingEngine
from app.rag.indexing.store import HybridVectorStore

logger = structlog.get_logger(__name__)


class HybridRetriever:
    """
    Production-grade Hybrid Retriever implementing:
    - Dense vector similarity (semantic capture)
    - Sparse BM25 token match (exact token/attribute capture)
    - Reciprocal Rank Fusion (RRF)
    - Attribute match boost reranking
    - Score threshold refusal path (INSUFFICIENT_CONTEXT)
    - Citation tagging: [DOC-1], [DOC-2], etc.
    """

    def __init__(
        self,
        store: HybridVectorStore,
        embedding_engine: EmbeddingEngine,
        rrf_k: int = rag_settings.RRF_K,
        min_threshold: float = rag_settings.MIN_SCORE_THRESHOLD,
    ):
        self.store = store
        self.embedding_engine = embedding_engine
        self.rrf_k = rrf_k
        self.min_threshold = min_threshold

    def search(
        self,
        query: str,
        top_k: int = rag_settings.TOP_K_RERANKED,
        overfetch_k: int = rag_settings.TOP_K_RETRIEVAL,
        domain: Optional[str] = None,
        resource_type: Optional[str] = None,
    ) -> List[SearchResult]:
        """
        Execute hybrid search with RRF score fusion and attribute reranking.
        """
        clean_query = query.strip()
        if not clean_query:
            return []

        # 1. Dense retrieval (Vector)
        query_vector = self.embedding_engine.embed_text(clean_query)
        dense_results = self.store.dense_search(
            query_vector=query_vector,
            top_k=overfetch_k,
            domain=domain,
            resource_type=resource_type,
        )

        # 2. Sparse retrieval (BM25)
        sparse_results = self.store.sparse_search(
            query_text=clean_query,
            top_k=overfetch_k,
            domain=domain,
        )

        # 3. Reciprocal Rank Fusion (RRF)
        # RRF score = sum(weight / (k + rank))
        chunk_map: Dict[str, Chunk] = {}
        dense_scores: Dict[str, float] = {}
        sparse_scores: Dict[str, float] = {}
        rrf_scores: Dict[str, float] = {}

        # Process dense ranks
        for rank, (chunk, score) in enumerate(dense_results, start=1):
            cid = chunk.chunk_id
            chunk_map[cid] = chunk
            dense_scores[cid] = score
            rrf_scores[cid] = rrf_scores.get(cid, 0.0) + (rag_settings.DENSE_WEIGHT / (self.rrf_k + rank))

        # Process sparse ranks
        for rank, (chunk, score) in enumerate(sparse_results, start=1):
            cid = chunk.chunk_id
            chunk_map[cid] = chunk
            sparse_scores[cid] = score
            rrf_scores[cid] = rrf_scores.get(cid, 0.0) + (rag_settings.SPARSE_WEIGHT / (self.rrf_k + rank))

        if not rrf_scores:
            logger.info("Hybrid search yielded 0 candidates", query=clean_query)
            return []

        # 4. Reranking: Attribute Match & Exact Token Boost
        reranked_scores: Dict[str, float] = {}
        query_tokens = set(clean_query.lower().split())

        for cid, rrf in rrf_scores.items():
            chunk = chunk_map[cid]
            boost = 1.0

            # If chunk resource_type is mentioned in query, grant significant boost
            if chunk.resource_type and chunk.resource_type.lower() in clean_query.lower():
                boost += 0.35

            # If chunk title matches query keywords
            title_tokens = set(chunk.title.lower().split())
            overlap = len(query_tokens.intersection(title_tokens))
            if overlap > 0:
                boost += 0.1 * min(overlap, 3)

            reranked_scores[cid] = rrf * boost

        # Sort by final score
        sorted_candidates = sorted(reranked_scores.items(), key=lambda x: x[1], reverse=True)

        # 5. Format Top-K Results and Assign Citation Tags
        results: List[SearchResult] = []
        for rank, (cid, final_score) in enumerate(sorted_candidates[:top_k], start=1):
            chunk = chunk_map[cid]

            # Enforce minimum threshold filter
            if final_score < self.min_threshold:
                logger.debug("Candidate score below minimum threshold", cid=cid, score=final_score, threshold=self.min_threshold)
                continue

            results.append(SearchResult(
                chunk_id=chunk.chunk_id,
                doc_id=chunk.doc_id,
                domain=chunk.domain,
                title=chunk.title,
                content=chunk.content,
                hcl_code=chunk.hcl_code,
                resource_type=chunk.resource_type,
                dense_score=dense_scores.get(cid, 0.0),
                sparse_score=sparse_scores.get(cid, 0.0),
                rrf_score=rrf_scores.get(cid, 0.0),
                final_score=final_score,
                citation_tag=f"[DOC-{rank}]",
                metadata=chunk.metadata,
            ))

        return results

    def assemble_grounded_context(
        self,
        query: str,
        top_k: int = rag_settings.TOP_K_RERANKED,
        max_tokens: int = rag_settings.MAX_CONTEXT_TOKENS,
    ) -> GroundedContext:
        """
        Assembles citation-tagged context within the strict token budget.
        """
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
            # Estimate tokens in this chunk (~4 chars per token)
            block = (
                f"{item.citation_tag} Reference: {item.title} ({item.domain})\n"
                f"Resource Type: {item.resource_type or 'General'}\n"
                f"Content:\n{item.content.strip()}\n"
            )
            est_tokens = len(block) // 4

            if token_count + est_tokens > max_tokens and accepted_citations:
                # Stop if we exceed token budget but already have top results
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
