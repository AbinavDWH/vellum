from typing import List, Optional, Dict, Any, Literal
from pydantic import BaseModel, Field, model_validator
from .database import DatabaseSchema
from .cloud import CloudPlan


class UniversalIR(BaseModel):
    intent: Literal[
        "create_database",
        "deploy_cloud",
        "create_database_and_deploy_cloud",
        "alter_database",
        "destroy_infrastructure",
        "inspect_schema",
        "deploy_static_site",
    ] = "create_database_and_deploy_cloud"
    description: Optional[str] = None
    database: Optional[DatabaseSchema] = None
    cloud: Optional[CloudPlan] = None
    dependencies: List[str] = Field(default_factory=list)
    assumptions: List[str] = Field(default_factory=list)
    estimated_cost_monthly: Optional[float] = None
    risk_level: Optional[str] = None  # "low", "medium", "high", "critical"
    site_source: Optional[Dict[str, Any]] = None  # {"type": "github" | "inline", "repo_url": "...", "files": {...}}
    implementation_plan: List[Dict[str, Any]] = Field(default_factory=list)

    @model_validator(mode="before")
    @classmethod
    def sanitize_ir(cls, data: Any) -> Any:
        if isinstance(data, dict):
            valid_intents = [
                "create_database",
                "deploy_cloud",
                "create_database_and_deploy_cloud",
                "alter_database",
                "destroy_infrastructure",
                "inspect_schema",
                "deploy_static_site",
            ]
            intent = str(data.get("intent") or "create_database_and_deploy_cloud").lower().strip()
            if intent not in valid_intents:
                intent = "create_database_and_deploy_cloud"
            data["intent"] = intent

            for k in ["dependencies", "assumptions"]:
                if data.get(k) is None:
                    data[k] = []
                elif isinstance(data[k], str):
                    data[k] = [data[k]]

            # Clean empty or "null" database/cloud
            db_val = data.get("database")
            if not db_val or db_val == "null" or (isinstance(db_val, dict) and not any(db_val.values())):
                data["database"] = None

            cloud_val = data.get("cloud")
            if not cloud_val or cloud_val == "null" or (isinstance(cloud_val, dict) and not any(cloud_val.values())):
                data["cloud"] = None

        return data


class ClarificationQuestion(BaseModel):
    question: str
    context: Optional[str] = None
    default_suggestion: Optional[str] = None
    options: List[str] = Field(default_factory=list)
    conflict_type: Optional[str] = None
    resource_name: Optional[str] = None


class ClarificationResponse(BaseModel):
    is_ready: bool
    questions: List[ClarificationQuestion] = Field(default_factory=list)
    raw_message: Optional[str] = None
