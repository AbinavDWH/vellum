import os
from pydantic_settings import BaseSettings
from pydantic import field_validator
from typing import Optional


class Settings(BaseSettings):
    # App
    PROJECT_NAME: str = "Vellum"
    VERSION: str = "1.0.0"
    DEBUG: bool = True
    API_PREFIX: str = "/api"

    # Cloud Environment
    CLOUD_ENV: str = "cloud"  # "cloud"
    CLOUD_PROVIDER: str = "aws"  # "aws", "azure", "gcp"

    # AWS Cloud
    DEFAULT_AWS_REGION: str = "us-east-1"
    AWS_ACCESS_KEY_ID: Optional[str] = None
    AWS_SECRET_ACCESS_KEY: Optional[str] = None

    # LM Studio (Local LLM)
    LM_STUDIO_URL: str = "http://localhost:1234/v1"
    LM_STUDIO_MODEL: str = "qwen3.5-4b"
    LM_STUDIO_TEMPERATURE: float = 0.2
    LM_STUDIO_MAX_TOKENS: int = 8192          # max OUTPUT tokens for IR generation
    LM_STUDIO_TIMEOUT: float = 180.0          # seconds per LM Studio request
    LLM_CHAT_MAX_TOKENS: int = 4096           # default for chat() and requirements synthesis
    LLM_ARCHITECT_MAX_TOKENS: int = 2048      # architect conversation replies
    LLM_GROQ_RETRY_MAX_TOKENS: int = 4096     # cap used after a Groq 429 (must still fit an IR plan)
    # LM Studio context length must be >= prompt (~8K) + max output. Set it in LM Studio, not here.
    REQUIREMENTS_MAX_CHARS: int = 12000       # ~3000 tokens; longer requirements.md is trimmed in the prompt

    # Groq API
    GROQ_API_KEY: Optional[str] =None
    GROQ_MODEL: str = "qwen/qwen3.8-27b"
    GROQ_FALLBACK_MODEL: str = "qwen/qwen3.8-27b"
    GROQ_API_URL: str = "https://api.groq.com/openai/v1"
    GROQ_TIMEOUT: float = 30.0

    # LLM Routing: "local" (Local LM Studio), "groq", or "hybrid"
    LLM_PROVIDER: str = "local"

    # Database (metadata storage)
    # Default to canonical vellum.db in backend directory, override with DATABASE_URL if configured
    DATABASE_URL: str = os.getenv(
        "DATABASE_URL",
        f"sqlite:///{os.path.abspath(os.path.join(os.path.dirname(__file__), '..', 'vellum.db'))}"
    )

    @field_validator("DATABASE_URL", mode="after")
    @classmethod
    def canonicalize_db_url(cls, v: str) -> str:
        if v and v.startswith("sqlite:///") and not v.startswith("sqlite:////") and not v.startswith("sqlite:///:memory:"):
            rel_path = v[len("sqlite:///"):]
            if rel_path.startswith("./"):
                rel_path = rel_path[2:]
            canon = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", rel_path))
            return f"sqlite:///{canon}"
        return v

    # Human in the loop
    HUMAN_APPROVAL_REQUIRED: bool = True
    AUTO_EXECUTE_READ_ONLY: bool = True

    # Execution Timeouts (M-18)
    APPLY_TIMEOUT_LOCAL: int = 120
    APPLY_TIMEOUT_PROD: int = 900  # 15 minutes

    # Terraform
    TERRAFORM_WORKSPACE: str = os.getenv(
        "TERRAFORM_WORKSPACE",
        os.path.abspath(os.path.join(os.path.dirname(__file__), '..', 'terraform-workspace'))
    )

    @field_validator("TERRAFORM_WORKSPACE", mode="after")
    @classmethod
    def canonicalize_workspace(cls, v: str) -> str:
        if v and not os.path.isabs(v):
            if v.startswith("./"):
                v = v[2:]
            canon = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", v))
            return canon
        return v
    TERRAFORM_BINARY: str = "terraform"

    model_config = {
        "env_file": [".env", "../.env"],
        "extra": "allow"
    }


settings = Settings()
