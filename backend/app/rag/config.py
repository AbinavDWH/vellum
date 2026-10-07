import os
from pydantic_settings import BaseSettings


class RAGSettings(BaseSettings):
    # Embedding Configuration
    EMBEDDING_PROVIDER: str = "lm_studio"  # "lm_studio" or "local_hash"
    EMBEDDING_MODEL: str = "text-embedding-nomic-embed-text-v1.5"
    EMBEDDING_DIMENSION: int = 768
    LM_STUDIO_EMBEDDINGS_URL: str = "http://localhost:1234/v1/embeddings"
    EMBEDDING_TIMEOUT: float = 30.0

    # Retrieval & RRF Tuning
    RRF_K: int = 60
    TOP_K_RETRIEVAL: int = 15
    TOP_K_RERANKED: int = 5
    MIN_SCORE_THRESHOLD: float = 0.012  # Below this, declare INSUFFICIENT_CONTEXT
    DENSE_WEIGHT: float = 0.5
    SPARSE_WEIGHT: float = 0.5

    # Context Budget
    MAX_CONTEXT_TOKENS: int = 2000

    # Storage Paths
    RAG_DATA_DIR: str = os.path.join(os.path.dirname(__file__), "data")
    KNOWLEDGE_BASE_DIR: str = os.path.join(os.path.dirname(__file__), "knowledge")

    model_config = {
        "env_file": ".env",
        "extra": "allow"
    }


rag_settings = RAGSettings()
