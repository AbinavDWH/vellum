import pytest
from app.healing.detector import DeterministicErrorDetector

@pytest.fixture
def detector():
    return DeterministicErrorDetector()

def test_detect_bucket_already_exists(detector):
    log = (
        "Error: creating Amazon S3 (Simple Storage) Bucket (my-corp-bucket-production): "
        "BucketAlreadyExists: The requested bucket name is not available. The bucket namespace is shared by all users in the system."
    )
    detected = detector.detect(log)
    assert detected is not None
    assert detected.signature == "BucketAlreadyExists"
    assert detected.error_class == "state_conflict"
    assert detected.is_unfixable is False
    assert detected.details.get("bucket_name") == "my-corp-bucket-production"

def test_detect_invalid_subnet_range(detector):
    log = (
        "Error: creating EC2 Subnet: InvalidSubnet.Range: The CIDR '10.0.1.0/24' conflicts with another subnet"
    )
    detected = detector.detect(log)
    assert detected is not None
    assert detected.signature == "InvalidSubnet.Range"
    assert detected.error_class == "addressing"
    assert detected.is_unfixable is False
    assert detected.details.get("cidr") == "10.0.1.0/24"

def test_detect_resource_not_found_ordering(detector):
    log = (
        "Error: ResourceNotFoundException: Cannot find dependency aws_security_group.web_sg\n"
        "status code: 404, request id: 12345"
    )
    detected = detector.detect(log)
    assert detected is not None
    assert detected.signature == "ResourceNotFound"
    assert detected.error_class == "ordering"
    assert detected.is_unfixable is False

def test_detect_hcl_syntax_error(detector):
    log = (
        "Error: Argument or block definition required\n"
        "on main.tf line 12: An argument or block definition is required here."
    )
    detected = detector.detect(log)
    assert detected is not None
    assert detected.signature == "HCLSyntaxError"
    assert detected.error_class == "generation"
    assert detected.is_unfixable is False

def test_detect_sql_syntax_error(detector):
    log = (
        "psycopg2.errors.SyntaxError: syntax error at or near \"CREAT\"\n"
        "LINE 1: CREAT TABLE users (\n"
    )
    detected = detector.detect(log)
    assert detected is not None
    assert detected.signature == "SQLSyntaxError"
    assert detected.error_class == "generation"
    assert detected.is_unfixable is False

def test_detect_connection_refused(detector):
    log = "Error: dial tcp 127.0.0.1:4566: connect: connection refused"
    detected = detector.detect(log)
    assert detected is not None
    assert detected.signature == "ConnectionRefused"
    assert detected.error_class == "transient"
    assert detected.is_unfixable is False

def test_detect_invalid_parameter_value(detector):
    log = "Error: InvalidParameterValue: The parameter instance_type=t2.huge is not valid"
    detected = detector.detect(log)
    assert detected is not None
    assert detected.signature == "InvalidParameterValue"
    assert detected.error_class == "generation"
    assert detected.is_unfixable is False

def test_detect_insufficient_instance_capacity(detector):
    log = "Error: InsufficientInstanceCapacity: We currently do not have sufficient t3.large capacity in the availability zone"
    detected = detector.detect(log)
    assert detected is not None
    assert detected.signature == "InsufficientInstanceCapacity"
    assert detected.error_class == "capacity"
    assert detected.is_unfixable is False

def test_detect_drift_conflict(detector):
    log = "Error: Object was modified outside of Terraform: Resource has been changed since last apply"
    detected = detector.detect(log)
    assert detected is not None
    assert detected.signature == "DriftConflict"
    assert detected.error_class in ["state", "state_conflict"]
    assert detected.is_unfixable is False

# Unfixable classes
def test_detect_access_denied_halts_unfixable(detector):
    log = (
        "Error: AccessDenied: User: arn:aws:iam::123456789012:user/deployer is not authorized to perform: "
        "iam:CreateRole on resource: arn:aws:iam::123456789012:role/app-role"
    )
    detected = detector.detect(log)
    assert detected is not None
    assert detected.signature == "AccessDenied"
    assert detected.error_class == "auth"
    assert detected.is_unfixable is True
    assert "HALT" in detected.recommended_action or "Never" in detected.recommended_action or "human" in detected.recommended_action.lower()

def test_detect_quota_exceeded_halts_unfixable(detector):
    log = "Error: LimitExceededException: The maximum number of VPCs has been reached for account 123456789012"
    detected = detector.detect(log)
    assert detected is not None
    assert detected.signature == "QuotaExceeded"
    assert detected.error_class == "quota"
    assert detected.is_unfixable is True

def test_detect_runtime_oom_timeout_halts_unfixable(detector):
    log = "Process terminated: out of memory (OOMKilled) while executing plan step"
    detected = detector.detect(log)
    assert detected is not None
    assert detected.signature == "RuntimeOOMOrTimeout"
    assert detected.error_class == "runtime"
    assert detected.is_unfixable is True

def test_detect_unknown_error_fallback(detector):
    log = "Some weird unexpected provider glitch: Error code 99999"
    detected = detector.detect(log)
    assert detected is not None
    assert detected.signature == "UnknownError"
    assert detected.error_class == "unknown"
    assert detected.is_unfixable is False
