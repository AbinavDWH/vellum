"""
Exit Tests for Module P-04: Secrets, Identity & Least Privilege.
Gate requirements to P-05:
1. Committed test secret is caught pre-merge and post-merge (history scan).
2. Role-permission audit shows zero wildcard data-plane permissions.
3. Rotation drill completes with zero failed requests during cutover.
4. Prompt/log scan proves no secret material reaches the LLM layer.
5. JIT access expires automatically and is logged.
"""
import datetime
import pytest
from app.credentials.manager import CredentialManager
from app.validation.container_security import ContainerSecurityScanner


def test_p04_exit_test_1_secret_caught_pre_merge():
    """
    Exit Test 1: Committed test secret is caught pre-merge and post-merge.
    """
    mock_commit_diff = """
    diff --git a/app/config.py b/app/config.py
    + AWS_SECRET_KEY = "AKIAIOSFODNN7EXAMPLE"
    + DB_PASS = "-----BEGIN RSA PRIVATE KEY-----"
    """
    findings = ContainerSecurityScanner.scan_for_secrets(mock_commit_diff)
    assert len(findings) >= 2
    types = [f["type"] for f in findings]
    assert "aws_access_key" in types
    assert "private_key" in types


def test_p04_exit_test_2_zero_wildcard_permissions():
    """
    Exit Test 2: Role-permission audit shows zero wildcard data-plane permissions.
    """
    mgr = CredentialManager()

    # Least-privilege compliant policy (specific actions and ARNs)
    compliant_policy = [
        {
            "Effect": "Allow",
            "Action": ["s3:GetObject", "s3:PutObject"],
            "Resource": ["arn:aws:s3:::vellum-plans-prod/*"]
        }
    ]
    audit_clean = mgr.audit_iam_least_privilege(compliant_policy)
    assert audit_clean["passed"] is True
    assert len(audit_clean["wildcard_violations"]) == 0

    # Over-permissive policy with wildcards
    violating_policy = [
        {
            "Effect": "Allow",
            "Action": ["s3:*"],
            "Resource": "*"
        }
    ]
    audit_failing = mgr.audit_iam_least_privilege(violating_policy)
    assert audit_failing["passed"] is False
    assert len(audit_failing["wildcard_violations"]) > 0


def test_p04_exit_test_3_dual_validity_rotation_zero_downtime():
    """
    Exit Test 3: Rotation drill completes with zero failed requests during cutover.
    """
    mgr = CredentialManager()
    db_name = "production_core"

    # Initial state
    creds_v1 = mgr.get_database_credentials(db_name)
    assert creds_v1["password"]

    # 1. Initiate dual-validity window
    window = mgr.initiate_dual_validity_rotation(db_name)
    assert window["both_passwords_accepted"] is True
    assert window["rotation_status"] == "DUAL_VALIDITY_ACTIVE"

    # Both old password and new password can connect during migration window
    active_window = mgr._rotation_windows[db_name]
    assert active_window["version_old"] == creds_v1["password"]
    assert active_window["version_new"] != creds_v1["password"]

    # 2. Complete cutover
    completed = mgr.complete_dual_validity_rotation(db_name)
    assert completed["rotation_status"] == "COMPLETED"

    # New password is now primary
    creds_v2 = mgr.get_database_credentials(db_name)
    assert creds_v2["password"] == active_window["version_new"]


def test_p04_exit_test_4_zero_secret_material_in_llm_layer():
    """
    Exit Test 4: Prompt/log scan proves no secret material reaches the LLM layer.
    """
    mgr = CredentialManager()
    mgr.get_database_credentials("analytics_db")

    # Clean prompt: uses abstract logical connection ID
    safe_prompt = "Create a database schema for connection_id: 'conn-prod-pg-01' with users and orders tables."
    isolation_res = mgr.verify_llm_prompt_isolation(safe_prompt)
    assert isolation_res["isolated"] is True
    assert len(isolation_res["leaked_store_keys"]) == 0

    # Contaminated prompt: contains embedded secret
    leaked_pass = mgr._secret_store["db_analytics_db_pass"]
    bad_prompt = f"Connecting using password: {leaked_pass} on host 10.0.1.5"
    leak_res = mgr.verify_llm_prompt_isolation(bad_prompt)
    assert leak_res["isolated"] is False
    assert "db_analytics_db_pass" in leak_res["leaked_store_keys"]


def test_p04_exit_test_5_jit_access_auto_expiry_and_audit():
    """
    Exit Test 5: JIT access expires automatically and is logged.
    """
    mgr = CredentialManager()

    # Request 60-minute JIT access
    lease = mgr.request_jit_access(
        operator_id="operator-devops-01",
        justification="INCIDENT-9821: Emergency production cache flush",
        duration_minutes=60
    )
    lease_id = lease["lease_id"]
    assert lease["active"] is True

    # Check status during active window
    status_active = mgr.verify_jit_lease_status(lease_id)
    assert status_active["active"] is True

    # Simulate check at 65 minutes (post-expiration)
    future_time = datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(minutes=65)
    status_expired = mgr.verify_jit_lease_status(lease_id, check_time=future_time)

    assert status_expired["active"] is False
    assert "expired automatically" in status_expired["reason"]
