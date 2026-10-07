import datetime
import hashlib
from typing import List, Dict, Any, Optional
from pydantic import BaseModel, Field


class Document(BaseModel):
    """Raw ingested document."""
    id: str
    domain: str  # terraform_aws, cis_benchmarks, past_plans, remediations
    title: str
    source_url: Optional[str] = None
    provider: str = "aws"
    version: Optional[str] = "5.0"
    content: str
    metadata: Dict[str, Any] = Field(default_factory=dict)
    created_at: str = Field(default_factory=lambda: datetime.datetime.utcnow().isoformat())


class Chunk(BaseModel):
    """Structured, code-aware chunk with citation metadata."""
    chunk_id: str
    doc_id: str
    domain: str
    title: str
    content: str
    hcl_code: Optional[str] = None
    resource_type: Optional[str] = None  # e.g., aws_s3_bucket, aws_vpc
    provider: str = "aws"
    version: Optional[str] = "5.0"
    metadata: Dict[str, Any] = Field(default_factory=dict)
    content_hash: str = ""
    token_estimate: int = 0

    def compute_hash(self) -> str:
        return hashlib.sha256(f"{self.domain}:{self.content}".encode("utf-8")).hexdigest()


class SearchResult(BaseModel):
    """Ranked search result with dense, sparse, and RRF scores."""
    chunk_id: str
    doc_id: str
    domain: str
    title: str
    content: str
    hcl_code: Optional[str] = None
    resource_type: Optional[str] = None
    dense_score: float = 0.0
    sparse_score: float = 0.0
    rrf_score: float = 0.0
    final_score: float = 0.0
    citation_tag: str = ""  # e.g., [DOC-1]
    metadata: Dict[str, Any] = Field(default_factory=dict)


class GroundedContext(BaseModel):
    """Context assembled for LLM prompt with citations and token budget."""
    formatted_context: str
    citations: List[SearchResult]
    total_tokens_estimate: int
    has_sufficient_context: bool
    domain_breakdown: Dict[str, int]
