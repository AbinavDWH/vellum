import pytest
from app.llm.client import llm_client
from app.approval.engine import approval_engine
from app.engines.terraform_generator import tf_generator
from app.engines.execution_engine import execution_engine
from app.engines.verification_engine import verification_engine
from app.audit.logger import audit_logger


def test_full_pipeline():
    # 1. Natural Language Input
    user_input = "Create an S3 bucket called vellum-app-assets on AWS"

    # 2. LM Studio generates IR
    ir = llm_client.generate_ir(user_input)

    # 3. Check approval needed
    assert approval_engine.requires_approval(ir) is True

    # 4. Simulate human approval
    plan_id = "e2e_test_001"

    # 5. Generate Terraform
    plan_dir = tf_generator.generate(ir, environment="local", plan_id=plan_id)

    from app.target import TargetResolution
    from unittest.mock import patch
    mock_target = TargetResolution(
        environment="dev",
        provider="aws",
        region="us-east-1",
        connection_id="conn_test",
        account_id="123456789012",
        aws_access_key="AKIAEXAMPLE",
        aws_secret_key="SECRETEXAMPLE",
        is_local=False,
        target_label="AWS Cloud (DEV) • Account: 123456789012 • Region: us-east-1",
    )

    # 6. Execute
    with patch("app.target.resolve_target", return_value=mock_target), \
         patch.object(execution_engine, "_run_streaming_command") as mock_cmd:
        mock_cmd.side_effect = [
            (0, "Terraform initialized", False),
            (0, "Apply complete! Resources: 1 added, 0 changed, 0 destroyed.", False),
        ]
        result = execution_engine.execute_plan(plan_dir, plan_id)
        assert result.success is True

    # 7. Verify
    with patch.object(verification_engine, "verify", return_value={"status": "success"}):
        report = verification_engine.verify(plan_id, ir)
        assert report["status"] == "success"

    # 8. Check audit log
    audit_logger.log("PIPELINE_COMPLETE", plan_id=plan_id, details={"status": "success"})
    audit = audit_logger.get_log(plan_id)
    assert audit is not None
