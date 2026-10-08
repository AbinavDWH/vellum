import pytest
from unittest.mock import patch
from app.engines.terraform_generator import TerraformGenerator
from app.engines.execution_engine import ExecutionEngine


def test_execution_cloud_fail_closed_without_credentials():
    """Verify execution engine fails closed when credentials are not configured."""
    test_ir = {
        "cloud": {
            "provider": "aws",
            "region": "us-east-1",
            "environment": "dev",
            "resources": [
                {"type": "object_storage", "name": "test-bucket", "properties": {"bucket_name": "vellum-test-exec-bucket"}}
            ],
        }
    }

    generator = TerraformGenerator()
    plan_dir = generator.generate(test_ir, environment="dev")

    engine = ExecutionEngine()
    result = engine.execute_plan(plan_dir, plan_id="test_001")

    assert result.success is False
    assert result.status == "failed"
    assert "authenticated AWS connection" in result.error_message


def test_execution_cloud_with_terraform_apply():
    """Verify execution engine applies Terraform successfully with credentials."""
    from app.target import TargetResolution

    test_ir = {
        "cloud": {
            "provider": "aws",
            "region": "us-east-1",
            "environment": "dev",
            "resources": [
                {"type": "object_storage", "name": "test-bucket", "properties": {"bucket_name": "vellum-test-exec-bucket"}}
            ],
        }
    }

    generator = TerraformGenerator()
    plan_dir = generator.generate(test_ir, environment="dev")

    engine = ExecutionEngine()
    mock_target = TargetResolution(
        environment="dev",
        provider="aws",
        region="us-east-1",
        connection_id="conn_1",
        account_id="123456789012",
        aws_access_key="AKIAEXAMPLE",
        aws_secret_key="SECRETEXAMPLE",
        is_local=False,
        target_label="AWS Cloud (DEV) • Account: 123456789012 • Region: us-east-1",
    )

    with patch("app.target.resolve_target", return_value=mock_target), \
         patch.object(engine, "_run_streaming_command") as mock_cmd:
        mock_cmd.side_effect = [
            (0, "Terraform has been successfully initialized!", False),
            (0, "Apply complete! Resources: 1 added, 0 changed, 0 destroyed.", False),
        ]
        result = engine.execute_plan(
            plan_dir,
            plan_id="test_002",
        )

        assert result.success is True
        assert result.resources_created == 1
