import pytest
import os
import shutil
import tempfile
from typing import List

from app.rag.models import Document, Chunk
from app.rag.ingestion.chunker import CodeAwareChunker
from app.rag.ingestion.pipeline import IngestionPipeline
from app.rag.indexing.embeddings import EmbeddingEngine
from app.rag.indexing.store import HybridVectorStore
from app.rag.retrieval.hybrid import HybridRetriever
from app.rag.service import RAGService


@pytest.fixture
def temp_dir():
    d = tempfile.mkdtemp(prefix="vellum_rag_test_")
    yield d
    shutil.rmtree(d, ignore_errors=True)


class TestCodeAwareChunker:
    """Layer 2: Test chunking never breaks HCL code blocks or semantics."""

    def test_chunking_preserves_hcl_blocks(self):
        chunker = CodeAwareChunker(target_tokens=350, max_tokens=600)
        hcl_content = """# AWS Storage Specification

## Resource: aws_s3_bucket
Here is how an S3 bucket is defined in HCL:

```hcl
resource "aws_s3_bucket" "my_bucket" {
  bucket        = "vellum-production-assets"
  force_destroy = true

  tags = {
    Environment = "prod"
    ManagedBy   = "vellum"
  }
}
```

This resource is essential for blob storage.
"""
        doc = Document(
            id="test_doc_s3",
            domain="terraform_aws",
            title="AWS Storage Specification",
            content=hcl_content,
        )

        chunks = chunker.chunk_document(doc)
        assert len(chunks) > 0

        # Verify that the chunk containing the HCL block has the complete block
        hcl_chunks = [c for c in chunks if c.hcl_code]
        assert len(hcl_chunks) >= 1
        hcl_chunk = hcl_chunks[0]

        assert 'resource "aws_s3_bucket" "my_bucket"' in hcl_chunk.content
        assert 'force_destroy = true' in hcl_chunk.content
        assert 'tags = {' in hcl_chunk.content
        assert hcl_chunk.resource_type == "aws_s3_bucket"


class TestEmbeddingEngine:
    """Layer 3: Test normalization, caching, and fallback."""

    def test_vector_normalization(self, temp_dir):
        db_path = os.path.join(temp_dir, "cache.db")
        engine = EmbeddingEngine(cache_db_path=db_path)

        raw_vec = [3.0, 4.0, 0.0]
        norm_vec = engine.normalize(raw_vec)
        # Length should be sqrt(3^2 + 4^2) = 5 -> [0.6, 0.8, 0.0]
        norm = sum(x * x for x in norm_vec)
        assert pytest.approx(norm, rel=1e-4) == 1.0

    def test_embedding_caching(self, temp_dir):
        db_path = os.path.join(temp_dir, "cache.db")
        engine = EmbeddingEngine(cache_db_path=db_path)

        text = "aws_s3_bucket configuration test"
        vec1 = engine.embed_text(text)
        assert len(vec1) == 768

        # Second embed must hit cache
        vec2 = engine.embed_text(text)
        assert vec1 == vec2


class TestHybridVectorStore:
    """Layer 4 & 6: Test dense + sparse BM25 indexing and retrieval."""

    def test_bm25_exact_token_match(self, temp_dir):
        db_path = os.path.join(temp_dir, "store.db")
        store = HybridVectorStore(db_path=db_path)

        chunk1 = Chunk(
            chunk_id="chk_1",
            doc_id="doc_1",
            domain="terraform_aws",
            title="RDS Subnet Group",
            content="Use aws_db_subnet_group to place RDS across multiple subnets.",
            resource_type="aws_db_subnet_group",
            token_estimate=50,
        )
        chunk2 = Chunk(
            chunk_id="chk_2",
            doc_id="doc_2",
            domain="terraform_aws",
            title="S3 Bucket Versioning",
            content="Use aws_s3_bucket_versioning to retain previous versions of objects.",
            resource_type="aws_s3_bucket",
            token_estimate=50,
        )

        dummy_vec = [1.0] + [0.0] * 767
        store.add_chunks([chunk1, chunk2], [dummy_vec, dummy_vec])

        # BM25 search for exact token 'aws_db_subnet_group'
        sparse_hits = store.sparse_search(query_text="aws_db_subnet_group", top_k=2)
        assert len(sparse_hits) > 0
        top_hit_chunk, top_score = sparse_hits[0]
        assert top_hit_chunk.chunk_id == "chk_1"
        assert top_score > 0.0


class TestHybridRetrieverAndReranking:
    """Layer 6 & 7: Test RRF fusion, reranking, and citation formatting."""

    def test_hybrid_search_with_rrf(self, temp_dir):
        db_path = os.path.join(temp_dir, "store.db")
        cache_path = os.path.join(temp_dir, "cache.db")
        store = HybridVectorStore(db_path=db_path)
        engine = EmbeddingEngine(cache_db_path=cache_path)
        retriever = HybridRetriever(store=store, embedding_engine=engine, min_threshold=0.001)

        c1 = Chunk(
            chunk_id="chk_rds",
            doc_id="doc_rds",
            domain="terraform_aws",
            title="RDS Instance Storage Throughput",
            content="storage_throughput is only valid when storage_type is gp3 and allocated_storage >= 400.",
            resource_type="aws_db_instance",
            token_estimate=40,
        )
        c2 = Chunk(
            chunk_id="chk_s3",
            doc_id="doc_s3",
            domain="terraform_aws",
            title="S3 Server Side Encryption",
            content="Enforce AES256 or aws:kms on all S3 buckets for CIS compliance.",
            resource_type="aws_s3_bucket",
            token_estimate=40,
        )

        v1 = engine.embed_text(c1.content)
        v2 = engine.embed_text(c2.content)
        store.add_chunks([c1, c2], [v1, v2])

        # Query specifically about storage_throughput
        results = retriever.search("Does aws_db_instance support storage_throughput?", top_k=2)
        assert len(results) > 0
        assert results[0].chunk_id == "chk_rds"
        assert results[0].citation_tag == "[DOC-1]"

    def test_grounded_context_token_budget(self, temp_dir):
        db_path = os.path.join(temp_dir, "store.db")
        cache_path = os.path.join(temp_dir, "cache.db")
        store = HybridVectorStore(db_path=db_path)
        engine = EmbeddingEngine(cache_db_path=cache_path)
        retriever = HybridRetriever(store=store, embedding_engine=engine, min_threshold=0.001)

        c1 = Chunk(
            chunk_id="chk_long",
            doc_id="doc_1",
            domain="terraform_aws",
            title="Very Long Resource Description",
            content="word " * 500,
            token_estimate=500,
        )
        v1 = engine.embed_text("word")
        store.add_chunks([c1], [v1])

        # Test context assembly with small token budget
        ctx = retriever.assemble_grounded_context(query="word", top_k=5, max_tokens=100)
        assert ctx.has_sufficient_context is True
        assert len(ctx.citations) == 1
        assert "[DOC-1]" in ctx.formatted_context


class TestProductionRAGIntegration:
    """End-to-end integration test of live knowledge base."""

    def test_live_knowledge_base_retrieval(self):
        service = RAGService()
        stats = service.get_stats()
        assert stats["total_chunks"] >= 30

        # Probe 1: Hallucination trap - storage_throughput
        res_throughput = service.search("Can I use storage_throughput with gp2 on aws_db_instance?", top_k=3)
        assert len(res_throughput) > 0
        combined_text = " ".join([r.content for r in res_throughput]).lower()
        assert "storage_throughput" in combined_text
        assert "gp3" in combined_text

        # Probe 2: CIS Benchmark - port 22 SSH ingress
        res_ssh = service.search("Is it allowed to open port 22 to 0.0.0.0/0?", top_k=3)
        assert len(res_ssh) > 0
        ssh_text = " ".join([r.content for r in res_ssh]).lower()
        assert "22" in ssh_text or "ssh" in ssh_text

        # Probe 3: S3 Encryption grounding
        ctx_s3 = service.assemble_grounded_context("How to enable server side encryption on S3?")
        assert ctx_s3.has_sufficient_context is True
        assert len(ctx_s3.citations) >= 1
        assert any(c.domain in ("terraform_aws", "cis_benchmarks") for c in ctx_s3.citations)


class TestQueryExpander:
    """Layer 5: Query Understanding and Acronym Expansion."""

    def test_acronym_expansion(self):
        from app.rag.query.expander import QueryExpander
        expander = QueryExpander()

        res = expander.expand("Create an SG for my RDS instance")
        assert "security group" in res.expanded_query.lower()
        assert "aws_db_instance" in res.expanded_query.lower()
        assert "aws_db_instance" in res.detected_resource_types
        assert "aws_security_group" in res.detected_resource_types

    def test_compound_query_decomposition(self):
        from app.rag.query.expander import QueryExpander
        expander = QueryExpander()

        res = expander.expand("I need a VPC network with an RDS database and an S3 bucket")
        assert len(res.sub_queries) >= 3


class TestGoldenBenchmarkEvaluation:
    """Layer 8: Golden Dataset Quantitative Benchmark."""

    def test_golden_dataset_metrics(self):
        service = RAGService()
        result = service.run_benchmark(top_k=5)

        assert result.total_queries >= 8
        assert result.hit_rate >= 0.85, f"Hit rate {result.hit_rate} below 0.85 threshold"
        assert result.mrr >= 0.70, f"MRR {result.mrr} below 0.70 threshold"
        assert result.passed_ci_gate is True
        assert result.avg_latency_ms < 500.0


class TestRAGObservability:
    """Layer 9: Retrieval Tracing and SLO Metrics."""

    def test_search_generates_trace(self):
        service = RAGService()
        unique_query = "Configure PostgreSQL on RDS with encryption unique test"
        service.search(unique_query, top_k=3)
        traces = service.get_traces(limit=5)
        assert len(traces) > 0

        latest = traces[0]
        assert latest["query"] == unique_query
        assert latest["latency_ms"] >= 0.0
        assert latest["chunks_retrieved"] > 0
        assert len(latest["citations"]) > 0

