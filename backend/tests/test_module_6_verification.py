import pytest
from app.engines.verification_engine import VerificationEngine


def test_verification():
    test_ir = {
        "cloud": {
            "provider": "aws",
            "region": "us-east-1",
            "resources": [
                {"type": "object_storage", "name": "test-bucket", "properties": {"bucket_name": "vellum-test-exec-bucket"}}
            ],
        }
    }

    verifier = VerificationEngine()
    report = verifier.verify(plan_id="test_001", expected_ir=test_ir)

    assert report["status"] == "success"
    assert report["drift_detected"] is False
    assert report["resources_verified"] > 0
