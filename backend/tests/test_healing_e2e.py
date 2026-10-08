import json
from pathlib import Path
import boto3
import pytest
from unittest.mock import patch, MagicMock
from app.config import settings
from app.database import SessionLocal
from app.models import PlanRecord, AuditLogRecord, HealingAttemptRecord, RemediationKBRecord
from app.schemas.ir import UniversalIR
from app.schemas.cloud import CloudPlan, CloudResource
from app.engines.terraform_generator import tf_generator
from app.engines.execution_engine import execution_engine
from app.healing.engine import self_healing_engine
from app.healing.detector import error_detector
from app.audit.logger import audit_logger

@pytest.fixture
def db_session():
    db = SessionLocal()
    yield db
    db.close()

def test_e2e_precreate_bucket_auto_import(db_session):
    """
    Checkpoint: Pre-create bucket -> run -> auto-import heal;
    audit shows HEAL_APPLIED; no human needed.
    """
    import uuid
    uid = uuid.uuid4().hex[:6]
    bucket_name = f"vellum-heal-bkt-{uid}"
    plan_id = f"test-plan-bucket-heal-{uid}"

    ir = UniversalIR(
        intent="deploy_cloud",
        cloud=CloudPlan(
            provider="aws",
            region="us-east-1",
            resources=[
                CloudResource(
                    id="b1",
                    name="app_storage",
                    type="object_storage",
                    properties={"bucket_name": bucket_name}
                )
            ]
        )
    )

    # Clean db
    db_session.query(PlanRecord).filter(PlanRecord.plan_id == plan_id).delete()
    db_session.query(AuditLogRecord).filter(AuditLogRecord.plan_id == plan_id).delete()
    db_session.commit()

    plan_dir = tf_generator.generate(ir, environment="dev", plan_id=plan_id)
    # Ensure fresh workspace with no prior tfstate
    for state_file in ["terraform.tfstate", "terraform.tfstate.backup"]:
        p = Path(plan_dir) / state_file
        if p.exists():
            p.unlink()
    plan_rec = PlanRecord(
        plan_id=plan_id,
        prompt="Create bucket",
        ir_json=ir.model_dump_json(),
        terraform_code=(Path(plan_dir) / "main.tf").read_text() if (Path(plan_dir) / "main.tf").exists() else "",
        status="running",
        risk_level="low",
    )
    db_session.add(plan_rec)
    db_session.commit()

    from app.target import TargetResolution
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

    # Execute plan
    events = []
    with patch("app.target.resolve_target", return_value=mock_target), \
         patch.object(execution_engine, "_run_streaming_command") as mock_cmd, \
         patch("app.healing.playbooks.subprocess.run") as mock_subproc:
        mock_subproc.return_value = MagicMock(returncode=0)
        mock_cmd.side_effect = [
            (0, "Terraform initialized", False),
            (1, f"Error: creating S3 Bucket ({bucket_name}): BucketAlreadyExists: The requested bucket name is not available.", False),
            (0, "Apply complete! Resources: 1 added, 0 changed, 0 destroyed.", False),
        ]
        res = execution_engine.execute_plan(
            plan_dir=str(plan_dir),
            plan_id=plan_id,
            current_ir=ir,
            on_event=lambda ev: events.append(ev),
            db=db_session,
        )

    assert res.success is True
    # Audit must show HEAL_APPLIED
    audits = db_session.query(AuditLogRecord).filter(
        AuditLogRecord.plan_id == plan_id,
        AuditLogRecord.event_type == "HEAL_APPLIED"
    ).all()
    assert len(audits) >= 1

def test_e2e_inject_cidr_overlap_recomputes_free_cidr(db_session, tmp_path):
    """
    Checkpoint: Inject CIDR overlap -> engine recomputes free CIDR;
    apply succeeds on attempt 2.
    """
    plan_id = "test-plan-cidr-overlap"
    ir = UniversalIR(
        intent="deploy_cloud",
        cloud=CloudPlan(
            provider="aws",
            region="us-east-1",
            resources=[
                CloudResource(
                    id="vpc1",
                    name="main_vpc",
                    type="virtual_network",
                    properties={"cidr_block": "10.0.0.0/16"}
                ),
                CloudResource(
                    id="sub1",
                    name="public_subnet",
                    type="subnet",
                    properties={"cidr_block": "10.0.1.0/24"}
                ),
                CloudResource(
                    id="sub2",
                    name="private_subnet",
                    type="subnet",
                    properties={"cidr_block": "10.0.1.0/24"}  # Injected overlap!
                ),
            ]
        )
    )

    plan_dir = tmp_path / plan_id
    plan_dir.mkdir(parents=True, exist_ok=True)
    tf_generator.generate(ir, environment="local", plan_id=plan_id)

    db_session.query(PlanRecord).filter(PlanRecord.plan_id == plan_id).delete()
    plan_rec = PlanRecord(
        plan_id=plan_id,
        prompt="VPC with subnets",
        ir_json=ir.model_dump_json(),
        terraform_code="",
        status="running",
        risk_level="low",
    )
    db_session.add(plan_rec)
    db_session.commit()

    overlap_log = (
        "Error: creating EC2 Subnet: InvalidSubnet.Range: The CIDR '10.0.1.0/24' conflicts with another subnet in the same VPC"
    )

    events = []
    # Test engine evaluating CIDR overlap
    should_reexec, patched_ir, new_hcl, detected, heal_rec = self_healing_engine.evaluate_and_heal(
        plan_id=plan_id,
        execution_id=None,
        attempt_number=1,
        log_text=overlap_log,
        current_ir=ir,
        plan_dir=str(plan_dir),
        on_event=lambda ev: events.append(ev),
        db=db_session,
    )

    assert should_reexec is True
    assert detected.signature == "InvalidSubnet.Range"
    assert heal_rec is not None
    assert heal_rec.status == "applied"
    assert heal_rec.is_auto_applied is True

    # Assert free CIDR was recomputed and distinct from 10.0.1.0/24
    sub2_cidr = patched_ir.cloud.resources[2].properties.get("cidr_block")
    assert sub2_cidr != "10.0.1.0/24"
    assert sub2_cidr in ["10.0.0.0/24", "10.0.2.0/24", "10.0.3.0/24"]

def test_e2e_inject_access_denied_halts_zero_auto_actions(db_session, tmp_path):
    """
    Checkpoint: Inject AccessDenied -> engine HALTS, zero auto-actions,
    human notification with diagnosis.
    """
    plan_id = "test-plan-access-denied"
    ir = UniversalIR(
        intent="deploy_cloud",
        cloud=CloudPlan(
            provider="aws",
            region="us-east-1",
            resources=[
                CloudResource(
                    id="sec1",
                    name="vault",
                    type="object_storage",
                    properties={"bucket_name": "vault-bucket"}
                )
            ]
        )
    )

    db_session.query(AuditLogRecord).filter(AuditLogRecord.plan_id == plan_id).delete()
    db_session.commit()

    auth_log = (
        "Error: AccessDenied: User: arn:aws:iam::123456789012:user/deployer is not authorized to perform: "
        "s3:CreateBucket on resource: arn:aws:s3:::vault-bucket"
    )

    events = []
    should_reexec, patched_ir, new_hcl, detected, heal_rec = self_healing_engine.evaluate_and_heal(
        plan_id=plan_id,
        execution_id=None,
        attempt_number=1,
        log_text=auth_log,
        current_ir=ir,
        plan_dir=str(tmp_path),
        on_event=lambda ev: events.append(ev),
        db=db_session,
    )

    # Must immediately HALT, zero auto-actions
    assert should_reexec is False
    assert patched_ir is None
    assert detected.signature == "AccessDenied"
    assert detected.is_unfixable is True
    assert heal_rec.status == "halted"
    assert heal_rec.is_auto_applied is False
    assert "diagnosis" in heal_rec.diff
    assert "credential" in heal_rec.reasoning.lower() or "policy" in heal_rec.reasoning.lower() or "auth" in heal_rec.reasoning.lower()

    # Emitted event is heal_halted
    halted_events = [e for e in events if e.get("event") == "heal_halted"]
    assert len(halted_events) >= 1
    assert halted_events[0]["error_class"] == "auth"

    # Audit shows HEAL_HALTED
    halt_audit = db_session.query(AuditLogRecord).filter(
        AuditLogRecord.plan_id == plan_id,
        AuditLogRecord.event_type == "HEAL_HALTED"
    ).first()
    assert halt_audit is not None

def test_e2e_unknown_attribute_proposal_approve_and_reject(db_session, tmp_path):
    """
    Checkpoint: Inject unknown attribute error -> LLM proposal shown with diff + reasoning;
    approve -> success; reject -> clean failure.
    """
    plan_id = "test-plan-unknown-attr"
    ir = UniversalIR(
        intent="deploy_cloud",
        cloud=CloudPlan(
            provider="aws",
            region="us-east-1",
            resources=[
                CloudResource(
                    id="vm1",
                    name="web_server",
                    type="compute_instance",
                    properties={"instance_type": "t2.invalid"}
                )
            ]
        )
    )

    plan_dir = tmp_path / plan_id
    plan_dir.mkdir(parents=True, exist_ok=True)
    (plan_dir / "main.tf").write_text("resource \"aws_instance\" \"web_server\" {}\n")

    db_session.query(PlanRecord).filter(PlanRecord.plan_id == plan_id).delete()
    db_session.query(RemediationKBRecord).filter(RemediationKBRecord.signature == "InvalidParameterValue").delete()
    plan_rec = PlanRecord(
        plan_id=plan_id,
        prompt="EC2 instance",
        ir_json=ir.model_dump_json(),
        terraform_code="resource \"aws_instance\" \"web_server\" {}\n",
        status="running",
        risk_level="low",
    )
    db_session.add(plan_rec)
    db_session.commit()

    err_log = "Error: InvalidParameterValue: Instance type 't2.invalid' is not recognized in region us-east-1"

    mock_llm_proposal = {
        "root_cause": "Invalid EC2 instance type t2.invalid",
        "fix_type": "ir_patch",
        "patch": {"resources[0].properties.instance_type": "t2.micro"},
        "reasoning": "Replace invalid instance type with standard t2.micro.",
        "confidence": 0.90,
        "risk_assessment": "low"
    }

    with patch("app.healing.proposer.llm_client.is_healthy", return_value=True), \
         patch("app.healing.proposer.llm_client.chat", return_value=mock_llm_proposal):
        should_reexec, patched_ir, _, detected, heal_rec = self_healing_engine.evaluate_and_heal(
            plan_id=plan_id,
            execution_id=None,
            attempt_number=1,
            log_text=err_log,
            current_ir=ir,
            plan_dir=str(plan_dir),
            db=db_session,
        )

        # Requires human approval
        assert should_reexec is False
        assert heal_rec is not None
        assert heal_rec.status == "awaiting_approval"
        assert heal_rec.remediation_class == "approve"
        assert "t2.micro" in str(heal_rec.patch_data)

        # Test Reject flow
        rejected_rec = self_healing_engine.reject_heal(
            plan_id=plan_id,
            attempt_number=1,
            reason="Operator prefers t3.micro instead",
            db=db_session,
        )
        assert rejected_rec.status == "rejected"

        # Verify reject audit
        rej_audit = db_session.query(AuditLogRecord).filter(
            AuditLogRecord.plan_id == plan_id,
            AuditLogRecord.event_type == "HEAL_REJECTED"
        ).first()
        assert rej_audit is not None

        # Reset status to test Approve flow
        rejected_rec.status = "awaiting_approval"
        db_session.commit()

        # Test Approve flow
        approved_rec = self_healing_engine.approve_heal(
            plan_id=plan_id,
            attempt_number=1,
            db=db_session,
        )
        assert approved_rec.status == "approved"

        # Verify approved audit
        appr_audit = db_session.query(AuditLogRecord).filter(
            AuditLogRecord.plan_id == plan_id,
            AuditLogRecord.event_type == "HEAL_APPLIED"
        ).first()
        assert appr_audit is not None

        # Verify plan record was patched
        updated_plan = db_session.query(PlanRecord).filter(PlanRecord.plan_id == plan_id).first()
        updated_ir_data = json.loads(updated_plan.ir_json)
        assert updated_ir_data["cloud"]["resources"][0]["properties"]["instance_type"] == "t2.micro"
