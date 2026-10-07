import pytest
from app.healing.detector import DetectedError
from app.healing.matrix import RemediationMatrix

def test_auto_allowed_bucket_already_exists():
    error = DetectedError(
        signature="BucketAlreadyExists",
        error_class="state_conflict",
        message="Bucket already exists",
        is_unfixable=False,
    )
    is_auto, rem_class, max_attempts = RemediationMatrix.evaluate(error)
    assert is_auto is True
    assert rem_class == "auto"
    assert max_attempts == 1

def test_auto_allowed_invalid_subnet_range():
    error = DetectedError(
        signature="InvalidSubnet.Range",
        error_class="addressing",
        message="Subnet CIDR overlaps",
        is_unfixable=False,
    )
    is_auto, rem_class, max_attempts = RemediationMatrix.evaluate(error)
    assert is_auto is True
    assert rem_class == "auto"
    assert max_attempts == 2

def test_auto_allowed_transient_connection_refused():
    error = DetectedError(
        signature="ConnectionRefused",
        error_class="transient",
        message="Connection refused",
        is_unfixable=False,
    )
    is_auto, rem_class, max_attempts = RemediationMatrix.evaluate(error)
    assert is_auto is True
    assert rem_class == "auto"
    assert max_attempts == 3

def test_blocked_unfixables_auth_access_denied():
    error = DetectedError(
        signature="AccessDenied",
        error_class="auth",
        message="User is not authorized",
        is_unfixable=True,
    )
    is_auto, rem_class, max_attempts = RemediationMatrix.evaluate(error)
    assert is_auto is False
    assert rem_class == "halted"
    assert max_attempts == 0

def test_blocked_unfixables_quota_exceeded():
    error = DetectedError(
        signature="QuotaExceeded",
        error_class="quota",
        message="VPC quota limit exceeded",
        is_unfixable=True,
    )
    is_auto, rem_class, max_attempts = RemediationMatrix.evaluate(error)
    assert is_auto is False
    assert rem_class == "halted"
    assert max_attempts == 0

def test_blocked_unfixables_runtime_oom():
    error = DetectedError(
        signature="RuntimeOOMOrTimeout",
        error_class="runtime",
        message="Out of memory killed",
        is_unfixable=True,
    )
    is_auto, rem_class, max_attempts = RemediationMatrix.evaluate(error)
    assert is_auto is False
    assert rem_class == "halted"
    assert max_attempts == 0

def test_security_widened_downgrades_to_human_approval():
    """Rule: No heal may widen security posture automatically."""
    error = DetectedError(
        signature="InvalidSubnet.Range",
        error_class="addressing",
        message="CIDR conflict",
        is_unfixable=False,
    )
    # Even if InvalidSubnet.Range is auto-allowed, widening security forces human approval
    is_auto, rem_class, max_attempts = RemediationMatrix.evaluate(
        error,
        is_security_widened=True
    )
    assert is_auto is False
    assert rem_class == "approve"

def test_destructive_patch_downgrades_to_human_approval():
    error = DetectedError(
        signature="BucketAlreadyExists",
        error_class="state_conflict",
        message="Bucket already exists",
        is_unfixable=False,
    )
    is_auto, rem_class, max_attempts = RemediationMatrix.evaluate(
        error,
        is_destructive=True
    )
    assert is_auto is False
    assert rem_class == "approve"

def test_circuit_broken_playbook_downgrades_to_human_approval():
    error = DetectedError(
        signature="InvalidSubnet.Range",
        error_class="addressing",
        message="CIDR conflict",
        is_unfixable=False,
    )
    is_auto, rem_class, max_attempts = RemediationMatrix.evaluate(
        error,
        circuit_broken=True
    )
    assert is_auto is False
    assert rem_class == "approve"

def test_promoted_kb_entry_is_auto_allowed():
    error = DetectedError(
        signature="CustomAttributeMisconfig",
        error_class="generation",
        message="Custom error",
        is_unfixable=False,
    )
    # Promoted playbook allows auto-fix
    is_auto, rem_class, _ = RemediationMatrix.evaluate(
        error,
        is_promoted=True,
        risk_level="low"
    )
    assert is_auto is True
    assert rem_class == "auto"
