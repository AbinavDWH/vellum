import re
from typing import Tuple
from app.environment.models import NamingValidationResult


class AWSNamingValidator:
    """Enforces and auto-corrects AWS resource naming constraints."""

    # S3: 3-63 chars, lowercase alphanumeric, hyphens, dots. Must start/end with alphanumeric. No uppercase. No underscores.
    S3_PATTERN = re.compile(r"^[a-z0-9][a-z0-9.-]{1,61}[a-z0-9]$")

    # RDS identifier: 1-63 chars, lowercase letter first, alphanumeric and hyphens, no consecutive hyphens, no trailing hyphen.
    RDS_PATTERN = re.compile(r"^[a-z][a-z0-9-]{0,62}$")

    # Security Group: 1-255 chars, alphanumeric, spaces, hyphens, underscores, dots
    SG_PATTERN = re.compile(r"^[a-zA-Z0-9_\-. ]{1,255}$")

    # IAM Role: 1-64 chars, alphanumeric, plus, equal, comma, period, at, hyphen
    IAM_PATTERN = re.compile(r"^[\w+=,.@-]{1,64}$")

    @classmethod
    def validate_and_fix(cls, resource_type: str, name: str) -> NamingValidationResult:
        norm_type = resource_type.lower()

        if norm_type in ["object_storage", "s3_bucket", "storage_bucket", "bucket", "aws_s3_bucket"]:
            return cls._validate_s3(name)
        elif norm_type in ["managed_database", "database", "rds", "aws_db_instance"]:
            return cls._validate_rds(name)
        elif norm_type in ["security_rule", "security_group", "aws_security_group"]:
            return cls._validate_sg(name)
        elif norm_type in ["iam_role", "iam_user", "aws_iam_role", "aws_iam_user"]:
            return cls._validate_iam(name)
        else:
            # Default generic resource
            fixed = re.sub(r"[^a-zA-Z0-9_-]", "-", name).strip("-")[:64]
            is_valid = fixed == name and len(name) > 0
            return NamingValidationResult(
                is_valid=is_valid,
                resource_type=resource_type,
                original_name=name,
                fixed_name=fixed or "resource-1",
                reason=None if is_valid else "Name normalized to standard character set",
            )

    @classmethod
    def _validate_s3(cls, name: str) -> NamingValidationResult:
        # Check standard constraints
        has_uppercase = any(c.isupper() for c in name)
        has_underscore = "_" in name
        has_double_dot = ".." in name

        if not has_uppercase and not has_underscore and not has_double_dot and cls.S3_PATTERN.match(name):
            return NamingValidationResult(
                is_valid=True,
                resource_type="object_storage",
                original_name=name,
                fixed_name=name,
                reason=None,
            )

        # Auto-fix: lowercase, replace underscores and spaces with hyphens, strip invalid chars
        fixed = name.lower()
        fixed = fixed.replace("_", "-").replace(" ", "-")
        fixed = re.sub(r"[^a-z0-9.-]", "", fixed)
        fixed = re.sub(r"\.{2,}", ".", fixed)
        fixed = re.sub(r"-{2,}", "-", fixed)

        # Must start and end with letter or digit
        fixed = fixed.strip(".-")

        # Length constraints: 3 to 63
        if len(fixed) < 3:
            fixed = (fixed + "-bucket")[:63]
            if len(fixed) < 3:
                fixed = "s3-bucket"
        elif len(fixed) > 63:
            fixed = fixed[:63].rstrip(".-")

        reasons = []
        if has_uppercase:
            reasons.append("uppercase characters not allowed in S3 bucket names")
        if has_underscore:
            reasons.append("underscores not allowed in S3 bucket names")
        if not reasons:
            reasons.append("name violates S3 bucket naming regex rules")

        return NamingValidationResult(
            is_valid=False,
            resource_type="object_storage",
            original_name=name,
            fixed_name=fixed,
            reason=f"Illegal S3 name: {', '.join(reasons)}",
        )

    @classmethod
    def _validate_rds(cls, name: str) -> NamingValidationResult:
        cleaned = name.lower()
        if cls.RDS_PATTERN.match(cleaned) and "--" not in cleaned and not cleaned.endswith("-"):
            return NamingValidationResult(
                is_valid=True,
                resource_type="managed_database",
                original_name=name,
                fixed_name=cleaned,
                reason=None,
            )

        fixed = re.sub(r"[^a-z0-9-]", "-", cleaned)
        fixed = re.sub(r"-{2,}", "-", fixed)
        # First char must be letter
        if not fixed or not fixed[0].isalpha():
            fixed = f"db-{fixed}"
        fixed = fixed[:63].rstrip("-")

        return NamingValidationResult(
            is_valid=False,
            resource_type="managed_database",
            original_name=name,
            fixed_name=fixed,
            reason="Illegal RDS identifier: must start with letter, lowercase, no consecutive hyphens",
        )

    @classmethod
    def _validate_sg(cls, name: str) -> NamingValidationResult:
        if cls.SG_PATTERN.match(name):
            return NamingValidationResult(
                is_valid=True,
                resource_type="security_rule",
                original_name=name,
                fixed_name=name,
                reason=None,
            )
        fixed = re.sub(r"[^a-zA-Z0-9_\-. ]", "-", name)[:255]
        return NamingValidationResult(
            is_valid=False,
            resource_type="security_rule",
            original_name=name,
            fixed_name=fixed or "default-sg",
            reason="Illegal security group name: invalid characters sanitized",
        )

    @classmethod
    def _validate_iam(cls, name: str) -> NamingValidationResult:
        if cls.IAM_PATTERN.match(name):
            return NamingValidationResult(
                is_valid=True,
                resource_type="iam_role",
                original_name=name,
                fixed_name=name,
                reason=None,
            )
        fixed = re.sub(r"[^\w+=,.@-]", "-", name)[:64]
        return NamingValidationResult(
            is_valid=False,
            resource_type="iam_role",
            original_name=name,
            fixed_name=fixed or "default-role",
            reason="Illegal IAM name: sanitized to permissible character set",
        )
