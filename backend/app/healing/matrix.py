from typing import Dict, Any, Tuple
from app.healing.detector import DetectedError


class RemediationMatrix:
    """Remediation policy and matrix rules enforcement."""

    # Default policy table for each signature
    RULES: Dict[str, Dict[str, Any]] = {
        "BucketAlreadyExists": {
            "class": "state_conflict",
            "auto_allowed": True,
            "max_attempts": 1,
            "default_action": "import",
            "description": "Import into state or suffix name",
        },
        "ResourceNotFound": {
            "class": "ordering",
            "auto_allowed": True,
            "max_attempts": 1,
            "default_action": "reorder",
            "description": "Add depends_on / reorder in IR",
        },
        "InvalidSubnet.Range": {
            "class": "addressing",
            "auto_allowed": True,
            "max_attempts": 2,
            "default_action": "cidr_recompute",
            "description": "Compute next free CIDR from existing VPC state",
        },
        "HCLSyntaxError": {
            "class": "generation",
            "auto_allowed": True,
            "max_attempts": 2,
            "default_action": "regenerate_hcl",
            "description": "Regenerate HCL from same IR (pre-apply, zero risk)",
        },
        "SQLSyntaxError": {
            "class": "generation",
            "auto_allowed": True,
            "max_attempts": 2,
            "default_action": "regenerate_sql",
            "description": "Regenerate DDL + dry-run validate (pre-execution)",
        },
        "ConnectionRefused": {
            "class": "transient",
            "auto_allowed": True,
            "max_attempts": 3,
            "default_action": "retry",
            "description": "Retry with exponential backoff + jitter",
        },
        "InvalidParameterValue": {
            "class": "generation",
            "auto_allowed": False,  # ⚠️ Approve unless in known map
            "max_attempts": 2,
            "default_action": "ir_patch",
            "description": "LLM proposes attribute patch",
        },
        "InsufficientInstanceCapacity": {
            "class": "capacity",
            "auto_allowed": False,  # ⚠️ Approve
            "max_attempts": 1,
            "default_action": "instance_fallback",
            "description": "Switch to fallback instance-class list",
        },
        "DriftConflict": {
            "class": "state",
            "auto_allowed": False,  # ⚠️ Conditional: approve if destructive diff
            "max_attempts": 1,
            "default_action": "replan",
            "description": "Refresh + replan; destructive diff -> approve",
        },
        "AccessDenied": {
            "class": "auth",
            "auto_allowed": False,  # 🚫 Block
            "max_attempts": 0,
            "default_action": "halt",
            "description": "HALT. Never auto-fix. Notify human with diagnosis",
        },
        "QuotaExceeded": {
            "class": "quota",
            "auto_allowed": False,  # 🚫 Block
            "max_attempts": 0,
            "default_action": "halt",
            "description": "HALT + human (cost/limit decision)",
        },
        "RuntimeOOMOrTimeout": {
            "class": "runtime",
            "auto_allowed": False,  # 🚫 Block
            "max_attempts": 0,
            "default_action": "halt",
            "description": "HALT + human",
        },
        "UnknownExecutionError": {
            "class": "unknown",
            "auto_allowed": False,
            "max_attempts": 2,
            "default_action": "ir_patch",
            "description": "LLM proposal -> human approval",
        },
        "UnknownError": {
            "class": "unknown",
            "auto_allowed": False,
            "max_attempts": 2,
            "default_action": "ir_patch",
            "description": "LLM proposal -> human approval",
        },
    }

    # Known safe attribute parameter fixes that can be auto-allowed if risk is low
    KNOWN_PARAMETER_MAP = {
        "force_destroy": True,
        "skip_final_snapshot": True,
        "enable_dns_hostnames": True,
    }

    @classmethod
    def evaluate(
        cls,
        detected: DetectedError,
        is_destructive: bool = False,
        is_security_widened: bool = False,
        circuit_broken: bool = False,
        is_promoted: bool = False,
        risk_level: str = "low",
    ) -> Tuple[bool, str, int]:
        """
        Evaluate whether remediation is auto-allowed or requires human approval.
        Returns (is_auto_allowed, remediation_class, max_attempts)
        remediation_class is one of: "auto", "approve", "halted".
        """
        # Rule 1: Auth, Quota, and Runtime are ALWAYS blocked
        if detected.error_class in ["auth", "quota", "runtime"] or detected.is_unfixable:
            return False, "halted", 0

        # Rule 2: Circuit broken playbooks are disabled from auto-fix
        if circuit_broken:
            return False, "approve", 1

        # Rule 3: No heal may widen security posture or delete resources automatically
        if is_security_widened or is_destructive:
            return False, "approve", 1

        # Rule 4: Promoted KB playbooks are pre-approved deterministic rules
        if is_promoted and risk_level == "low":
            return True, "auto", 2

        rule = cls.RULES.get(detected.signature, cls.RULES.get("UnknownExecutionError", {}))
        max_attempts = rule.get("max_attempts", 2)
        base_auto = rule.get("auto_allowed", False)

        # Check known parameter map for InvalidParameterValue
        if detected.signature == "InvalidParameterValue":
            param = detected.metadata.get("parameter")
            if param and param in cls.KNOWN_PARAMETER_MAP and risk_level == "low":
                base_auto = True

        remediation_class = "auto" if base_auto else "approve"
        return base_auto, remediation_class, max_attempts


remediation_matrix = RemediationMatrix()
