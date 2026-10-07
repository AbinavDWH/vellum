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

    # 6. Execute
    result = execution_engine.execute_plan(plan_dir, plan_id)
    assert result.success is True

    # 7. Verify
    report = verification_engine.verify(plan_id, ir)
    assert report["status"] == "success"

    # 8. Check audit log
    audit_logger.log("PIPELINE_COMPLETE", plan_id=plan_id, details={"status": "success"})
    audit = audit_logger.get_log(plan_id)
    assert audit is not None
