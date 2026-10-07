import os
from pydantic_settings import BaseSettings
from typing import Optional


class Settings(BaseSettings):
    # App
    PROJECT_NAME: str = "Vellum"
    VERSION: str = "1.0.0"
    DEBUG: bool = True
    API_PREFIX: str = "/api"

    # Cloud Environment
    CLOUD_ENV: str = "local"  # "local" or "cloud"
    CLOUD_PROVIDER: str = "aws"  # "aws", "azure", "gcp"

    # LocalStack / AWS
    LOCALSTACK_URL: str = "http://localhost:4566"
    LOCALSTACK_REGION: str = "us-east-1"
    AWS_ACCESS_KEY_ID: str = "test"
    AWS_SECRET_ACCESS_KEY: str = "test"

    # LM Studio (Local LLM)
    LM_STUDIO_URL: str = "http://localhost:1234/v1"
    LM_STUDIO_MODEL: str = "qwen3.5-4b"
    LM_STUDIO_TEMPERATURE: float = 0.2
    LM_STUDIO_MAX_TOKENS: int = 20000

    # Groq API
    GROQ_API_KEY: Optional[str] =None
    GROQ_MODEL: str = "openai/gpt-oss-120b"
    GROQ_FALLBACK_MODEL: str = "openai/gpt-oss-20b"
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
    TERRAFORM_BINARY: str = "terraform"

    model_config = {
        "env_file": [".env", "../.env"],
        "extra": "allow"
    }


settings = Settings()
