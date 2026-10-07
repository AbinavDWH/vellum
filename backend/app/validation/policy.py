from enum import Enum
from typing import Tuple, Optional
from app.schemas.ir import UniversalIR


class RiskLevel(str, Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


class PolicyEngine:
    """Enforces organizational policies and determines operation risk levels."""

    @classmethod
    def evaluate_risk(cls, ir: UniversalIR) -> Tuple[RiskLevel, bool, Optional[str]]:
        """
        Returns (risk_level, requires_confirmation_text, confirmation_phrase)
        """
        intent = ir.intent.lower()

        # Critical operations
        if "destroy" in intent or "delete" in intent:
            return (RiskLevel.CRITICAL, True, "DESTROY")

        # Check for drop statements or deletion
        if ir.description and any(w in ir.description.lower() for w in ["drop table", "delete all", "terminate"]):
            return (RiskLevel.CRITICAL, True, "DELETE")

        # High risk: alter operations
        if "alter" in intent or (ir.description and "alter" in ir.description.lower()):
            return (RiskLevel.HIGH, True, "CONFIRM")

        # Medium risk: create operations
        if any(w in intent for w in ["create", "deploy"]):
            return (RiskLevel.MEDIUM, False, None)

        # Low risk: inspect / read
        return (RiskLevel.LOW, False, None)

    @classmethod
    def validate_public_access(cls, ir: UniversalIR) -> Tuple[bool, Optional[str]]:
        """
        Public-read allowed ONLY for website-flagged buckets.
        Returns (is_allowed, error_message).
        """
        if ir.cloud:
            for res in ir.cloud.resources:
                if res.type in ["object_storage", "storage_bucket", "s3_bucket", "static_site", "website_hosting"]:
                    is_web = bool(
                        res.properties.get("website") is True
                        or res.properties.get("static_site") is True
                        or res.type in ["static_site", "website_hosting"]
                        or "website" in res.name.lower()
                    )
                    acl = res.properties.get("acl", "private")
                    is_public = acl in ["public-read", "public-read-write"] or res.properties.get("public") is True
                    if is_public and not is_web:
                        return False, f"Bucket '{res.name}' has public-read requested without website hosting enabled. Public-read is allowed ONLY for website-flagged buckets."
        return True, None
