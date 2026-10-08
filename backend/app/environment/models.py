import hashlib
import json
import time
from typing import Dict, Any, List, Optional
from pydantic import BaseModel, Field


class EnvironmentSnapshot(BaseModel):
    snapshot_id: str
    provider: str = "aws"
    region: str = "us-east-1"
    timestamp: float = Field(default_factory=time.time)
    ttl_seconds: int = 60
    unavailable: bool = False

    # Discovered external cloud state
    buckets: List[str] = Field(default_factory=list)
    vpcs: List[Dict[str, Any]] = Field(default_factory=list)
    subnets: List[Dict[str, Any]] = Field(default_factory=list)
    security_groups: List[Dict[str, Any]] = Field(default_factory=list)
    rds_instances: List[Dict[str, Any]] = Field(default_factory=list)
    iam_roles: List[str] = Field(default_factory=list)
    iam_users: List[str] = Field(default_factory=list)
    instance_offerings: List[str] = Field(default_factory=list)

    # Local workspace state tracking (resources already managed by Vellum)
    managed_resources: Dict[str, List[str]] = Field(default_factory=dict)

    # Deterministic SHA-256 fingerprint
    snapshot_hash: str = ""

    def compute_hash(self) -> str:
        """Deterministic fingerprint of discovered cloud state."""
        canonical = {
            "provider": self.provider,
            "region": self.region,
            "buckets": sorted(self.buckets),
            "vpcs": sorted(self.vpcs, key=lambda x: x.get("cidr_block", "")),
            "subnets": sorted(self.subnets, key=lambda x: (x.get("vpc_id", ""), x.get("cidr_block", ""))),
            "security_groups": sorted(self.security_groups, key=lambda x: (x.get("vpc_id", ""), x.get("name", ""))),
            "rds_instances": sorted(self.rds_instances, key=lambda x: x.get("identifier", "")),
            "iam_roles": sorted(self.iam_roles),
            "iam_users": sorted(self.iam_users),
        }
        encoded = json.dumps(canonical, sort_keys=True).encode("utf-8")
        return hashlib.sha256(encoded).hexdigest()

    def is_stale(self, max_age: float = 60.0) -> bool:
        return (time.time() - self.timestamp) > max_age


class ConflictReport(BaseModel):
    resource_id: str
    resource_type: str
    original_name: str
    conflict_type: str  # name_exists, cidr_overlap, illegal_name, instance_unavailable, protected_name
    strategy: str       # reuse, rename, ask-user, auto-recompute, auto-fallback, auto-fix, fail-fast
    proposed_action: str
    new_value: Optional[str] = None
    options: List[str] = Field(default_factory=list)
    status_chip: str
    details: Dict[str, Any] = Field(default_factory=dict)


class NamingValidationResult(BaseModel):
    is_valid: bool
    resource_type: str
    original_name: str
    fixed_name: str
    reason: Optional[str] = None
