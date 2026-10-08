import pytest
from unittest.mock import patch, MagicMock
from app.engines.verification_engine import VerificationEngine


def test_verification_fail_closed_without_credentials():
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

    assert report["status"] == "incident"
    assert report["drift_detected"] is False
    assert "without valid AWS credentials" in report.get("error_message", "") or "Fail-Closed" in report.get("error_message", "")


def test_verification_success_with_cloud_credentials():
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
    with patch("boto3.client") as mock_boto:
        mock_sts = MagicMock()
        mock_sts.get_caller_identity.return_value = {"Account": "123456789012"}
        mock_s3 = MagicMock()
        mock_s3.list_buckets.return_value = {"Buckets": [{"Name": "vellum-test-exec-bucket"}]}
        mock_ec2 = MagicMock()
        mock_ec2.describe_vpcs.return_value = {"Vpcs": []}
        mock_ec2.describe_subnets.return_value = {"Subnets": []}
        mock_ec2.describe_route_tables.return_value = {"RouteTables": []}
        mock_ec2.describe_internet_gateways.return_value = {"InternetGateways": []}
        mock_ec2.describe_security_groups.return_value = {"SecurityGroups": []}
        mock_ec2.describe_nat_gateways.return_value = {"NatGateways": []}
        mock_ec2.describe_addresses.return_value = {"Addresses": []}

        def client_side_effect(service, **kwargs):
            if service == "sts":
                return mock_sts
            if service == "s3":
                return mock_s3
            return mock_ec2

        mock_boto.side_effect = client_side_effect

        report = verifier.verify(
            plan_id="test_002",
            expected_ir=test_ir,
            aws_access_key="AKIAEXAMPLE",
            aws_secret_key="SECRETEXAMPLE",
        )

        assert report["status"] == "success"
        assert report["drift_detected"] is False
        assert report["resources_verified"] > 0
