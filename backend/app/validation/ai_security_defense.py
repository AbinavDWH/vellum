"""
Security hardening, abuse prevention, prompt-injection defense, and two-person approval governance.
Implements controls for Module P-08 (Security Hardening, Abuse & AI-Specific Defense).
"""
import re
import datetime
from typing import Dict, Any, List, Optional
import structlog
from app.approval.engine import ApprovalEngine

logger = structlog.get_logger(__name__)


# Known prompt-injection and jailbreak attack patterns
PROMPT_INJECTION_PATTERNS = [
    re.compile(r"(?i)ignore\s+(?:all\s+)?(?:previous|prior)\s+instructions"),
    re.compile(r"(?i)system\s+override"),
    re.compile(r"(?i)you\s+are\s+now\s+(?:in\s+)?dan\s+mode"),
    re.compile(r"(?i)(?:execute|run)\s+(?:bash|sh|rm\s+-rf|curl\s+|wget\s+)"),
    re.compile(r"(?i)(?:delete|drop)\s+(?:all\s+)?(?:tables|databases|infrastructure)"),
    re.compile(r"(?i)disregard\s+safety"),
]


class AISecurityDefenseEngine:
    """
    AI Security, CSPM Posture, and Abuse Defense:
    1. Cloud Security Posture Management (CSPM) checks
    2. Tenant quotas, rate limiting, and abuse protection
    3. Multi-layer prompt injection defense & structural allowlist
    4. Two-Person Rule (multi-signature) for CRITICAL actions
    5. Dependency vulnerability remediation SLA tracking
    """

    CVE_SLAS_HOURS = {
        "CRITICAL": 24,    # 1 day
        "HIGH": 168,       # 7 days
        "MEDIUM": 720,     # 30 days
    }

    def __init__(self):
        self._tenant_quotas: Dict[str, Dict[str, Any]] = {}
        self._multisig_approvals: Dict[str, List[str]] = {}  # plan_id -> list of approver_ids

    # 1. Posture Scanner
    @classmethod
    def run_posture_scan(cls, infrastructure_state: List[Dict[str, Any]]) -> Dict[str, Any]:
        findings = []
        for res in infrastructure_state:
            res_id = res.get("id", "unknown")
            if res.get("type") == "s3" and res.get("public_read") is True:
                findings.append({
                    "id": res_id,
                    "severity": "CRITICAL",
                    "issue": "S3 bucket has public read access enabled",
                })
            if res.get("type") == "rds" and res.get("publicly_accessible") is True:
                findings.append({
                    "id": res_id,
                    "severity": "CRITICAL",
                    "issue": "RDS instance publicly accessible",
                })
        return {
            "clean": len(findings) == 0,
            "findings_count": len(findings),
            "findings": findings,
        }

    # 2. Quotas & Rate Limiting
    def check_tenant_quota(
        self,
        tenant_id: str,
        plan_cost_units: int = 1,
        max_hourly_units: int = 10
    ) -> Dict[str, Any]:
        now = datetime.datetime.now(datetime.timezone.utc)
        record = self._tenant_quotas.setdefault(tenant_id, {"used_units": 0, "window_start": now})

        # Reset window if > 1 hour
        if (now - record["window_start"]).total_seconds() > 3600:
            record["used_units"] = 0
            record["window_start"] = now

        if record["used_units"] + plan_cost_units > max_hourly_units:
            return {
                "allowed": False,
                "tenant_id": tenant_id,
                "used": record["used_units"],
                "limit": max_hourly_units,
                "reason": "Hourly quota exceeded. Rate limited to prevent budget drain.",
            }

        record["used_units"] += plan_cost_units
        return {
            "allowed": True,
            "tenant_id": tenant_id,
            "used": record["used_units"],
            "limit": max_hourly_units,
        }

    # 3. Prompt Injection Defense
    @classmethod
    def sanitize_and_validate_prompt(cls, prompt_text: str) -> Dict[str, Any]:
        """
        Scans input for jailbreaks and ensures prompt cannot break out of IR schema generation.
        """
        detected_attacks = []
        for pattern in PROMPT_INJECTION_PATTERNS:
            if pattern.search(prompt_text):
                detected_attacks.append(pattern.pattern)

        passed = len(detected_attacks) == 0
        return {
            "safe": passed,
            "detected_attacks_count": len(detected_attacks),
            "patterns_matched": detected_attacks,
            "sanitized": prompt_text.replace("<script>", "").replace("</script>", ""),
        }

    # 4. Two-Person Rule for Critical Actions
    def submit_approval(
        self,
        plan_id: str,
        risk_level: str,
        approver_id: str
    ) -> Dict[str, Any]:
        """
        Enforces separation of duties:
        - LOW / MEDIUM risk: 1 approver required.
        - HIGH / CRITICAL risk: 2 distinct human approvers required.
        - AI is never allowed to approve its own plans.
        """
        if approver_id.lower() in ["ai", "vellum_agent", "system"]:
            return {
                "approved": False,
                "error": "Autonomous AI approval rejected. Human operator approval mandatory.",
            }

        approvers = self._multisig_approvals.setdefault(plan_id, [])

        if approver_id in approvers:
            return {
                "approved": False,
                "error": f"Operator '{approver_id}' has already approved this plan. Second distinct approver required.",
            }

        approvers.append(approver_id)

        required_count = 2 if risk_level.lower() in ["high", "critical"] else 1
        can_execute = len(approvers) >= required_count

        return {
            "plan_id": plan_id,
            "risk_level": risk_level,
            "approvers_count": len(approvers),
            "required_approvers": required_count,
            "execution_permitted": can_execute,
            "status": "APPROVED" if can_execute else "AWAITING_SECOND_SIGNATURE",
        }

    # 5. Dependency Patch SLA Check
    @classmethod
    def verify_patch_sla(
        cls,
        cve_id: str,
        severity: str,
        elapsed_hours: float
    ) -> Dict[str, Any]:
        max_hours = cls.CVE_SLAS_HOURS.get(severity.upper(), 720)
        within_sla = elapsed_hours <= max_hours
        return {
            "cve_id": cve_id,
            "severity": severity,
            "elapsed_hours": elapsed_hours,
            "max_hours_sla": max_hours,
            "within_sla": within_sla,
        }
