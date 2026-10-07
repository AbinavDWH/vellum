import os
import json
import pytest
from unittest.mock import MagicMock, patch
from pathlib import Path

from app.config import settings
from app.engines.execution_engine import execution_engine, WorkspaceLock
from app.engines.verification_engine import verification_engine
from app.schemas.api import ExecutionResult
from app.schemas.ir import UniversalIR
from app.models import PlanRecord, ConnectionRecord
from app.credentials.manager import credential_manager


def test_m18_s3_create_bucket_region_matrix():
    """
    Test Fix 3: S3 CreateBucket must omit CreateBucketConfiguration for us-east-1,
    and include LocationConstraint for any other AWS region.
    """
    tf_hcl = 'resource "aws_s3_bucket" "test_b" { bucket = "vellum-bucket-test-123" }'

    for region in ["us-east-1", "eu-west-1", "ap-south-1"]:
        with patch("boto3.client") as mock_boto:
            mock_s3 = MagicMock()
            mock_boto.return_value = mock_s3

            res = execution_engine._execute_via_boto3(
                tf_content=tf_hcl,
                plan_id="plan_test_s3_matrix",
                start_time=0.0,
                log=lambda m: None,
                target_env="local",
                target_region=region,
            )

            assert res.success is True
            mock_boto.assert_called_with(
                "s3",
                region_name=region,
                endpoint_url=settings.LOCALSTACK_URL,
                aws_access_key_id="test",
                aws_secret_access_key="test",
            )

            if region == "us-east-1":
                mock_s3.create_bucket.assert_called_with(Bucket="vellum-bucket-test-123")
            else:
                mock_s3.create_bucket.assert_called_with(
                    Bucket="vellum-bucket-test-123",
                    CreateBucketConfiguration={"LocationConstraint": region},
                )


def test_m18_direct_boto3_prohibited_in_prod():
    """
    Test Fix 2: Calling direct boto3 provisioning in PROD/STAGING is strictly prohibited.
    """
    with pytest.raises(RuntimeError) as exc_info:
        execution_engine._execute_via_boto3(
            tf_content='resource "aws_s3_bucket" "b" { bucket = "prod-bucket" }',
            plan_id="plan_prod_forbidden",
            start_time=0.0,
            log=lambda m: None,
            target_env="prod",
            target_region="us-east-1",
        )
    assert "Direct boto3 provisioning is prohibited in PROD/STAGING" in str(exc_info.value)


def test_m18_prod_timeout_reconciling_and_no_boto3_fallback(tmp_path, db_session):
    """
    Test Fix 1 & 2: When terraform apply times out in PROD:
    - Child process is deterministically reaped.
    - State is reconciled via terraform refresh.
    - Status is 'unknown_reconciling'.
    - Recovery options are returned.
    - Zero boto3 fallback calls are made.
    """
    workspace = tmp_path / "plan_timeout_test"
    workspace.mkdir()
    (workspace / "main.tf").write_text('provider "aws" {}\nresource "aws_vpc" "v" { cidr_block = "10.0.0.0/16" }')

    # Seed plan record
    plan_rec = PlanRecord(
        plan_id="plan_timeout_test",
        prompt="Deploy VPC in prod",
        ir_json=json.dumps({"cloud": {"environment": "prod", "region": "us-east-1", "resources": []}}),
        status="executing",
    )
    db_session.add(plan_rec)
    db_session.commit()

    # Mock init succeeding
    with patch.object(execution_engine, "_run_streaming_command") as mock_run_cmd, \
         patch.object(execution_engine, "_reconcile_state") as mock_reconcile, \
         patch.object(execution_engine, "_execute_via_boto3") as mock_boto:

        # 1st call is init (returncode=0, out="init success", timed_out=False)
        # 2nd call is apply (returncode=-1, out="timeout", timed_out=True)
        mock_run_cmd.side_effect = [
            (0, "Terraform has been successfully initialized!", False),
            (-1, "Process exceeded timeout limit. Terminating child process...", True),
        ]
        mock_reconcile.return_value = ["aws_vpc.v"]

        res = execution_engine.execute_plan(
            plan_dir=str(workspace),
            plan_id="plan_timeout_test",
            db=db_session,
        )

        assert res.success is False
        assert res.status == "unknown_reconciling"
        assert "Apply timed out" in res.error_message
        assert res.recovery_options == ["retry_apply", "import_and_adopt", "rollback"]
        assert res.resources_created == 1

        mock_reconcile.assert_called_once()
        mock_boto.assert_not_called()


def test_m18_prod_apply_partial_failure_honest_status(tmp_path, db_session):
    """
    Test Fix 4: Partial apply failure in PROD returns status 'failed' (never 'completed'),
    reconciles state, and provides operator recovery options.
    """
    workspace = tmp_path / "plan_partial_fail"
    workspace.mkdir()
    (workspace / "main.tf").write_text('provider "aws" {}\nresource "aws_vpc" "v" {}\nresource "aws_db_instance" "db" {}')

    plan_rec = PlanRecord(
        plan_id="plan_partial_fail",
        prompt="Deploy DB in prod",
        ir_json=json.dumps({"cloud": {"environment": "prod", "region": "us-east-1", "resources": []}}),
        status="executing",
    )
    db_session.add(plan_rec)
    db_session.commit()

    with patch.object(execution_engine, "_run_streaming_command") as mock_run_cmd, \
         patch.object(execution_engine, "_reconcile_state") as mock_reconcile, \
         patch("app.healing.self_healing_engine.evaluate_and_heal") as mock_heal, \
         patch.object(execution_engine, "_execute_via_boto3") as mock_boto:

        # init succeeds, apply fails with code 1
        mock_run_cmd.side_effect = [
            (0, "Terraform initialized", False),
            (1, "Error creating DB instance: Subnet group missing", False),
        ]
        # Healing says cannot auto-heal (halt)
        mock_detector_result = MagicMock()
        mock_detector_result.signature = "MissingSubnetGroup"
        mock_detector_result.diagnosis = "DB Subnet group required for RDS"
        mock_detector_result.is_unfixable = True
        mock_heal.return_value = (False, None, None, mock_detector_result, None)

        mock_reconcile.return_value = ["aws_vpc.v"]

        res = execution_engine.execute_plan(
            plan_dir=str(workspace),
            plan_id="plan_partial_fail",
            db=db_session,
        )

        assert res.success is False
        assert res.status == "halted"
        assert "MissingSubnetGroup" in res.error_message
        assert res.resources_created == 1
        assert "retry_apply" in res.recovery_options
        assert "rollback" in res.recovery_options

        mock_boto.assert_not_called()


def test_m18_verification_fail_closed_on_missing_or_test_credentials(db_session):
    """
    Test Fix 5: If environment is PROD and credentials are missing or LocalStack test keys,
    verification halts with status 'incident', refuses to report drift, and logs INCIDENT_TARGET_MISMATCH.
    """
    plan_ir = UniversalIR(
        intent="create_production_db",
        cloud={
            "provider": "aws",
            "environment": "prod",
            "region": "us-east-1",
            "resources": [{"name": "primary_rds", "type": "managed_database"}],
        }
    )

    # 1. Test missing credentials
    report = verification_engine.verify(
        plan_id="plan_verify_test",
        expected_ir=plan_ir,
        environment="prod",
        aws_access_key=None,
        aws_secret_key=None,
        region="us-east-1",
        db=db_session,
    )

    assert report["status"] == "incident"
    assert report["drift_detected"] is False  # Refuses to falsely report drift
    assert "Verification halted" in report["error_message"]
    assert report["audited_target_label"] == "AWS Cloud (PROD) [ABORTED: TARGET MISMATCH]"
    assert report["target_environment"] == "prod"

    # 2. Test LocalStack "test" credentials against PROD target
    report_test_keys = verification_engine.verify(
        plan_id="plan_verify_test",
        expected_ir=plan_ir,
        environment="prod",
        aws_access_key="test",
        aws_secret_key="test",
        region="us-east-1",
        db=db_session,
    )

    assert report_test_keys["status"] == "incident"
    assert report_test_keys["drift_detected"] is False
    assert "Refusing to verify against LocalStack (Fail-Closed)" in report_test_keys["error_message"]


def test_m18_verification_header_labels_for_prod_and_local():
    """
    Test Fix 5 & 6: Verification returns audited account, region, and target label.
    """
    ir = UniversalIR(
        intent="test_ir",
        cloud={"provider": "aws", "environment": "local", "region": "us-west-2", "resources": []}
    )

    # Local environment
    local_report = verification_engine.verify(
        plan_id="plan_local_test",
        expected_ir=ir,
        environment="local",
        region="us-west-2",
    )
    assert local_report["target_environment"] == "local"
    assert "LocalStack (Simulation)" in local_report["audited_target_label"]
    assert "us-west-2" in local_report["audited_target_label"]

    # PROD with authenticated credentials
    with patch("boto3.client") as mock_boto:
        mock_sts = MagicMock()
        mock_sts.get_caller_identity.return_value = {"Account": "353681408434", "Arn": "arn:aws:iam::353681408434:user/test"}
        mock_s3 = MagicMock()
        mock_s3.list_buckets.return_value = {"Buckets": []}
        mock_ec2 = MagicMock()
        mock_ec2.describe_vpcs.return_value = {"Vpcs": []}

        def client_side_effect(service, **kwargs):
            if service == "sts":
                return mock_sts
            if service == "s3":
                return mock_s3
            if service == "ec2":
                return mock_ec2
            return MagicMock()

        mock_boto.side_effect = client_side_effect

        prod_ir = UniversalIR(
            intent="test_prod_ir",
            cloud={"provider": "aws", "environment": "prod", "region": "us-east-1", "resources": []}
        )

        prod_report = verification_engine.verify(
            plan_id="plan_prod_auth",
            expected_ir=prod_ir,
            environment="prod",
            aws_access_key="AKIAEXAMPLE",
            aws_secret_key="SECRETEXAMPLE",
            region="us-east-1",
        )

        assert prod_report["target_environment"] == "prod"
        assert prod_report["audited_account_id"] == "353681408434"
        assert prod_report["audited_region"] == "us-east-1"
        assert "AWS Cloud (PROD) • Account: 353681408434 (us-east-1)" == prod_report["audited_target_label"]
        assert prod_report["status"] == "success"


def test_m18_workspace_lock_prevents_concurrency(tmp_path):
    """
    Test Fix 1: Workspace single-writer lock prevents concurrent apply races.
    """
    workspace = tmp_path / "plan_locked_workspace"
    workspace.mkdir()
    (workspace / "main.tf").write_text('provider "aws" {}\n')

    lock1 = WorkspaceLock(workspace)
    assert lock1.acquire() is True

    # Attempt to execute plan while workspace is locked
    res = execution_engine.execute_plan(
        plan_dir=str(workspace),
        plan_id="plan_concurrent_test",
    )

    assert res.success is False
    assert res.status == "halted"
    assert "locked by another running execution" in res.error_message

    lock1.release()

    # Once released, lock can be acquired again
    lock2 = WorkspaceLock(workspace)
    assert lock2.acquire() is True
    lock2.release()


def test_m18_rollback_execution(tmp_path):
    """
    Test Fix 4: Rollback runs terraform destroy with state invariant check.
    """
    workspace = tmp_path / "plan_rollback_test"
    workspace.mkdir()
    (workspace / "main.tf").write_text('provider "aws" {}\n')

    with patch.object(execution_engine, "_run_streaming_command") as mock_run_cmd, \
         patch.object(execution_engine, "_get_terraform_state_resources") as mock_state:

        mock_run_cmd.return_value = (0, "Destroy complete! Resources: 1 destroyed.", False)
        mock_state.return_value = []  # 0 remaining resources in state

        res = execution_engine.rollback(
            plan_dir=str(workspace),
            plan_id="plan_rollback_test",
        )

        assert res.success is True
        assert res.status == "completed"
        assert res.resources_deleted == 1
        assert "Rollback completed cleanly" in res.error_message
