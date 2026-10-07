from typing import List, Optional, Dict, Any
from pydantic import BaseModel, Field, model_validator


class CloudResource(BaseModel):
    id: Optional[str] = None
    type: str  # e.g., "virtual_network", "subnet", "security_rule", "managed_database", "object_storage", "compute_instance"
    name: str
    properties: Dict[str, Any] = Field(default_factory=dict)
    depends_on: List[str] = Field(default_factory=list)
    tags: Dict[str, str] = Field(default_factory=dict)
    status_chip: Optional[str] = None
    is_dependency: Optional[bool] = False
    dependency_reason: Optional[str] = None

    @model_validator(mode="before")
    @classmethod
    def sanitize_resource(cls, data: Any) -> Any:
        if isinstance(data, dict):
            if data.get("properties") is None:
                data["properties"] = {}
            if data.get("depends_on") is None:
                data["depends_on"] = []
            elif isinstance(data["depends_on"], str):
                data["depends_on"] = [data["depends_on"]]
            if data.get("tags") is None:
                data["tags"] = {}
            if "name" in data and isinstance(data["name"], str):
                data["name"] = data["name"].strip().replace(" ", "_")
        return data


class CloudPlan(BaseModel):
    provider: str = "aws"  # "aws", "azure", "gcp"
    region: str = "us-east-1"
    environment: str = "local"  # "local", "dev", "prod"
    resources: List[CloudResource] = Field(default_factory=list)
    outputs: Dict[str, str] = Field(default_factory=dict)

    @model_validator(mode="before")
    @classmethod
    def sanitize_cloud_plan(cls, data: Any) -> Any:
        if isinstance(data, dict):
            if data.get("resources") is None:
                data["resources"] = []
            if data.get("outputs") is None:
                data["outputs"] = {}
            if not data.get("provider"):
                data["provider"] = "aws"
            if not data.get("region"):
                data["region"] = "us-east-1"
            if not data.get("environment"):
                data["environment"] = "local"
        return data
