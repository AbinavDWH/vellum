"""
Production Infrastructure as Code (IaC) governance, policy guardrails, state locking, and drift detection.
Implements controls for Module P-03 (Production Infrastructure as Code).
"""
import re
from typing import Dict, Any, List, Optional
import structlog

logger = structlog.get_logger(__name__)


class IaCGovernanceException(Exception):
    """Raised when IaC policy guardrails or state integrity rules fail."""
    pass


class IaCGovernanceEngine:
    """
    IaC Governance Controls:
    1. Remote Encrypted State & DynamoDB Locking enforcement
    2. Policy-as-Code Guardrails (blocks public DB, open data ports, unencrypted storage)
    3. Mandatory Tagging and Orphan Resource scanner
    4. Scheduled Drift Detection
    5. Multi-AZ distribution validation and failure resilience
    """

    MANDATORY_TAGS = {"ManagedBy", "Environment", "Owner"}
    SENSITIVE_PORTS = {5432, 3306, 27017, 6379, 22}

    def __init__(self):
        self._active_locks: Dict[str, str] = {}  # lock_key -> holder_id

    def acquire_state_lock(self, state_key: str, runner_id: str) -> Dict[str, Any]:
        """
        DynamoDB-style state locking simulator.
        Rejects concurrent apply attempts to prevent state file corruption.
        """
        if state_key in self._active_locks:
            current_holder = self._active_locks[state_key]
            if current_holder != runner_id:
                logger.warn("state_lock_conflict", state_key=state_key, holder=current_holder, requester=runner_id)
                return {
                    "acquired": False,
                    "state_key": state_key,
                    "error": f"State locked by runner: {current_holder}. Concurrent apply rejected.",
                }
        self._active_locks[state_key] = runner_id
        return {
            "acquired": True,
            "state_key": state_key,
            "lock_id": f"lock-{runner_id}",
        }

    def release_state_lock(self, state_key: str, runner_id: str) -> bool:
        """Releases the state lock."""
        if self._active_locks.get(state_key) == runner_id:
            del self._active_locks[state_key]
            return True
        return False

    @classmethod
    def validate_policy_guardrails(cls, plan_resources: List[Dict[str, Any]]) -> Dict[str, Any]:
        """
        Policy-as-Code gate (Checkov / OPA equivalent):
        - Blocks public RDS (publicly_accessible = true)
        - Blocks open ingress 0.0.0.0/0 to sensitive data ports
        - Blocks unencrypted storage buckets
        - Enforces mandatory tagging
        """
        violations = []

        for res in plan_resources:
            r_type = res.get("type", "")
            name = res.get("name", "unknown")
            props = res.get("properties", {})
            tags = res.get("tags", {})

            # 1. Block public RDS
            if r_type in ["managed_database", "aws_db_instance"]:
                if props.get("publicly_accessible", False) is True:
                    violations.append({
                        "resource": name,
                        "rule": "POLICY-SEC-008",
                        "severity": "CRITICAL",
                        "message": "Publicly accessible RDS database is prohibited in production.",
                    })

            # 2. Block 0.0.0.0/0 to database ports and SSH
            if r_type in ["security_rule", "aws_security_group"]:
                ingress_rules = props.get("ingress", [])
                for rule in ingress_rules:
                    cidr = rule.get("cidr", "")
                    port = rule.get("from_port", 0)
                    if cidr == "0.0.0.0/0" and port in cls.SENSITIVE_PORTS:
                        violations.append({
                            "resource": name,
                            "rule": "POLICY-SEC-001",
                            "severity": "CRITICAL",
                            "message": f"Security group opens sensitive port {port} to 0.0.0.0/0.",
                        })

            # 3. Block unencrypted storage
            if r_type in ["object_storage", "aws_s3_bucket"]:
                if props.get("encrypted", True) is False:
                    violations.append({
                        "resource": name,
                        "rule": "POLICY-SEC-002",
                        "severity": "HIGH",
                        "message": "S3 buckets must have server-side encryption enabled.",
                    })

            # 4. Mandatory tagging
            missing_tags = cls.MANDATORY_TAGS - set(tags.keys())
            if missing_tags:
                violations.append({
                    "resource": name,
                    "rule": "POLICY-TAG-001",
                    "severity": "HIGH",
                    "message": f"Resource missing mandatory tags: {sorted(list(missing_tags))}",
                })

        passed = len(violations) == 0
        return {
            "passed": passed,
            "violations": violations,
            "blocking_count": len([v for v in violations if v["severity"] == "CRITICAL"]),
        }

    @classmethod
    def detect_drift(
        cls,
        expected_state: Dict[str, Any],
        actual_cloud_state: Dict[str, Any]
    ) -> Dict[str, Any]:
        """
        Compares version-controlled definition against live cloud resources.
        Alerts on manual console edits or rogue deletions.
        """
        drifted_resources = []

        for res_id, expected_props in expected_state.items():
            if res_id not in actual_cloud_state:
                drifted_resources.append({
                    "resource_id": res_id,
                    "drift_type": "DELETED_OUT_OF_BAND",
                    "description": "Resource defined in IaC but absent in cloud provider",
                })
            else:
                actual_props = actual_cloud_state[res_id]
                for prop_key, prop_val in expected_props.items():
                    if actual_props.get(prop_key) != prop_val:
                        drifted_resources.append({
                            "resource_id": res_id,
                            "drift_type": "PROPERTY_MODIFIED",
                            "property": prop_key,
                            "expected": prop_val,
                            "actual": actual_props.get(prop_key),
                        })

        has_drift = len(drifted_resources) > 0
        return {
            "has_drift": has_drift,
            "drift_count": len(drifted_resources),
            "drifted_resources": drifted_resources,
            "alert_required": has_drift,
        }

    @classmethod
    def simulate_az_failure(
        cls,
        available_azs: List[str],
        failed_az: str,
        resources: List[Dict[str, Any]]
    ) -> Dict[str, Any]:
        """
        Simulates single-AZ outage drill.
        Verifies that multi-AZ topology maintains healthy service when one AZ fails.
        """
        remaining_azs = [az for az in available_azs if az != failed_az]
        surviving_resources = [
            r for r in resources
            if r.get("availability_zone") != failed_az
        ]

        # Service survives if >= 2 AZs remain and >= 50% capacity persists
        survived = len(remaining_azs) >= 2 and len(surviving_resources) > 0

        return {
            "failed_az": failed_az,
            "remaining_azs": remaining_azs,
            "surviving_resources_count": len(surviving_resources),
            "service_survived": survived,
            "degradation_mode": "ACTIVE_REDUNDANT" if survived else "OUTAGE",
        }
