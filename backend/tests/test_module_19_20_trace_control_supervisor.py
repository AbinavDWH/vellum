import os
import json
import time
import pytest
from unittest.mock import MagicMock, patch
from pathlib import Path
from fastapi.testclient import TestClient

from app.config import settings
from app.database import get_db
from app.models import PlanRecord, WireTraceRecordModel, SupervisorEventModel
from app.schemas.api import ExecutionPolicy
from app.tracing.wire_trace import wire_trace_collector
from app.healing.supervisor import healing_supervisor
from app.engines.execution_engine import execution_engine
from app.engines.verification_engine import verification_engine
from app.main import app, _chat_cancellation_tokens


@pytest.fixture
def client(db_session):
    def override_get_db():
        try:
            yield db_session
        finally:
            pass
    app.dependency_overrides[get_db] = override_get_db
    c = TestClient(app)
    yield c
    app.dependency_overrides.clear()


# ==============================================================================
# M-19 Tests: Wire Trace Capture, Masking, CloudTrail Cross-Check & Three-Leg
# ==============================================================================

def test_m19_wire_trace_recording_and_masking(db_session):
    """
    Test that Boto3 and Terraform calls are intercepted, sanitized, and stored with SHA-256 fingerprint.
    """
    plan_id = "plan_test_trace_01"
    wire_trace_collector.clear_plan(plan_id)

    # 1. Record an SDK trace with sensitive keys
    record = wire_trace_collector.record_call(
        plan_id=plan_id,
        service="s3",
        operation="CreateBucket",
        source="vellum-sdk",
        params_masked={
            "Bucket": "my-sensitive-bucket",
            "password": "super-secret-pw",
            "aws_secret_access_key": "AKIA123SECRET",
        },
        http_status=200,
        request_id="req-aws-12345",
        latency_ms=145.2,
        db=db_session,
    )

    assert record.seq == 1
    assert record.params_masked["Bucket"] == "my-sensitive-bucket"
    assert record.params_masked["password"] == "[REDACTED_SECRET]"
    assert record.params_masked["aws_secret_access_key"] == "[REDACTED_SECRET]"
    assert record.http_status == 200

    # 2. Record a Terraform line trace via record_terraform_call
    tf_rec = wire_trace_collector.record_terraform_call(
        plan_id=plan_id,
        service="ec2",
        operation="CreateVpc",
        http_status=200,
        params={"resource": "aws_vpc.main_vpc", "id": "vpc-0123456789abcdef0"},
        db=db_session,
    )
    assert tf_rec is not None
    assert tf_rec.service == "ec2"
    assert tf_rec.operation == "CreateVpc"
    assert tf_rec.source == "terraform"
    assert tf_rec.params_masked.get("id") == "vpc-0123456789abcdef0"

    # 3. Export bundle and check SHA-256 hash
    json_str, sha256_hash = wire_trace_collector.export_trace_json(plan_id, db=db_session)
    assert len(json_str) > 0
    assert len(sha256_hash) == 64  # SHA-256 hex string


def test_m19_three_leg_verification_pass(db_session):
    """
    Test Three-Leg Agreement when Leg 1 (Intent), Leg 2 (Wire Trace), and Leg 3 (Cloud Truth) agree.
    """
    plan_id = "plan_three_leg_pass"
    wire_trace_collector.clear_plan(plan_id)

    # Seed intent (IR)
    ir_dict = {
        "cloud": {
            "provider": "aws",
            "environment": "local",
            "resources": [
                {"name": "test_bucket", "type": "s3_bucket", "properties": {"bucket_name": "app-assets-bucket"}}
            ],
        }
    }

    # Seed Wire Trace
    wire_trace_collector.record_call(
        plan_id=plan_id,
        service="s3",
        operation="CreateBucket",
        source="terraform",
        params_masked={"Bucket": "app-assets-bucket"},
        http_status=200,
        request_id="req-s3-111",
        latency_ms=80,
        db=db_session,
    )

    # Mock Boto3 clients in verification_engine.verify
    with patch("boto3.client") as mock_boto:
        mock_s3 = MagicMock()
        mock_ec2 = MagicMock()
        mock_s3.list_buckets.return_value = {"Buckets": [{"Name": "app-assets-bucket"}]}
        mock_ec2.describe_vpcs.return_value = {"Vpcs": []}

        def boto_client_side_effect(service, **kwargs):
            if service == "s3":
                return mock_s3
            return mock_ec2

        mock_boto.side_effect = boto_client_side_effect

        report = verification_engine.verify(
            plan_id=plan_id,
            expected_ir=ir_dict,
            environment="dev",
            aws_access_key="test_key",
            aws_secret_key="test_secret",
            db=db_session,
        )

        assert report["status"] == "success"
        assert "three_leg" in report
        three_leg = report["three_leg"]
        assert three_leg["all_legs_agreed"] is True
        assert three_leg["overall_status"] == "pass"
        assert three_leg["zombie_events_detected"] is False
        assert three_leg["orphan_resources_detected"] is False


def test_m19_three_leg_verification_orphan_and_zombies(db_session):
    """
    Test that extra CloudTrail calls or untracked resources trigger orphan_detected / zombie_events_detected.
    """
    plan_id = "plan_three_leg_zombie"
    wire_trace_collector.clear_plan(plan_id)

    ir_dict = {
        "cloud": {
            "provider": "aws",
            "environment": "prod",
            "resources": [
                {"name": "main_vpc", "type": "vpc", "properties": {"cidr_block": "10.0.0.0/16"}}
            ],
        }
    }

    # Mock Boto3 and CloudTrail returning extra zombie calls
    with patch("boto3.client") as mock_boto, \
         patch.object(wire_trace_collector, "verify_cloudtrail_crosscheck") as mock_ct:

        mock_s3 = MagicMock()
        mock_ec2 = MagicMock()
        mock_s3.list_buckets.return_value = {"Buckets": []}
        mock_ec2.describe_vpcs.return_value = {"Vpcs": [{"CidrBlock": "10.0.0.0/16"}]}

        def boto_client_side_effect(service, **kwargs):
            if service == "s3":
                return mock_s3
            return mock_ec2

        mock_boto.side_effect = boto_client_side_effect

        mock_ct.return_value = {
            "total_traces": 1,
            "confirmed_traces": 1,
            "matched_events": 1,
            "zombie_detected": True,
            "zombie_events": [{"event_name": "CreateBucket", "username": "vellum-zombie"}],
            "confirmed_badge": False,
        }

        report = verification_engine.verify(
            plan_id=plan_id,
            expected_ir=ir_dict,
            environment="prod",
            aws_access_key="test_key",
            aws_secret_key="test_secret",
            db=db_session,
        )

        assert "three_leg" in report
        three_leg = report["three_leg"]
        assert three_leg["zombie_events_detected"] is True
        assert three_leg["overall_status"] == "orphan_detected"


# ==============================================================================
# M-20 Tests: Execution Termination, Targeted Auto-Rollback & Healing Supervisor
# ==============================================================================

def test_m20_execution_termination_sigint_and_sigkill():
    """
    Test two-stage termination:
    - Click 1: Graceful SIGINT
    - Click 2: Force SIGKILL with child process reap and state reconcile
    """
    plan_id = "plan_proc_term_test"
    mock_proc = MagicMock()
    mock_proc.poll.return_value = None  # process is running

    execution_engine._active_processes[plan_id] = mock_proc

    # Test Graceful SIGINT (with plan_dir passed for state reconcile)
    with patch.object(execution_engine, "_reconcile_state") as mock_reconcile:
        res = execution_engine.terminate_execution(plan_id=plan_id, force=False, plan_dir="/tmp/test_dir")
        assert res["mode"] == "sigint"
        assert res["status"] == "cancelled"
        mock_proc.send_signal.assert_called_once()
        mock_reconcile.assert_called_once()

    # Re-register process for SIGKILL test
    execution_engine._active_processes[plan_id] = mock_proc
    mock_proc.kill.reset_mock()

    with patch.object(execution_engine, "_reconcile_state") as mock_reconcile:
        res = execution_engine.terminate_execution(plan_id=plan_id, force=True, plan_dir="/tmp/test_dir")
        assert res["mode"] == "sigkill"
        assert res["status"] == "cancelled"
        mock_proc.kill.assert_called_once()
        mock_reconcile.assert_called_once()


def test_m20_targeted_auto_rollback_and_deletion_protection(tmp_path):
    """
    Test targeted rollback:
    - Destroys ONLY resources created in this run (target_resources)
    - Skips resources marked deletion_protection: true with PROTECTED_KEPT
    """
    plan_dir = tmp_path / "plan_rollback_target"
    plan_dir.mkdir()
    (plan_dir / "main.tf").write_text('resource "aws_vpc" "v" {}\nresource "aws_db_instance" "db" {}')

    # Mock _run_streaming_command and state list
    with patch.object(execution_engine, "_run_streaming_command") as mock_run_cmd, \
         patch.object(execution_engine, "_get_terraform_state_resources") as mock_get_state:

        mock_run_cmd.return_value = (0, "Destroy complete! Resources: 1 destroyed.", False)
        mock_get_state.return_value = []

        res = execution_engine.rollback(
            plan_dir=str(plan_dir),
            plan_id="plan_rollback_target",
            target_resources=["aws_vpc.v", "aws_db_instance.db"],
            skip_protected=["aws_db_instance.db"],
        )

        assert res.success is True
        called_cmd = mock_run_cmd.call_args[0][0]
        assert "-target=aws_vpc.v" in called_cmd
        assert "-target=aws_db_instance.db" not in called_cmd
        assert "[PROTECTED_KEPT] Resource 'aws_db_instance.db'" in res.terraform_output


def test_m20_always_on_healing_supervisor_streaming_and_stall(db_session):
    """
    Test line-by-line scanning from second 0 and stall detector (>180s).
    """
    plan_id = "plan_supervisor_test"
    healing_supervisor.clear_plan(plan_id)

    # 1. Execution start emits MONITOR
    healing_supervisor.on_execution_start(
        plan_id=plan_id,
        target_env="local",
        region="us-east-1",
        db=db_session,
    )

    feed = healing_supervisor.get_feed(plan_id)
    assert len(feed) >= 1
    assert feed[0].phase == "MONITOR"

    # 2. Line with CIDR overlap should emit DETECT and DECIDE
    healing_supervisor.on_stream_line(
        plan_id=plan_id,
        line="Error: CidrConflictException: The CIDR '10.0.0.0/16' conflicts with another VPC",
        db=db_session,
    )

    feed = healing_supervisor.get_feed(plan_id)
    detect_events = [e for e in feed if e.phase == "DETECT"]
    decide_events = [e for e in feed if e.phase == "DECIDE"]
    assert len(detect_events) >= 1
    assert detect_events[0].signature == "InvalidSubnet.Range"
    assert len(decide_events) >= 1
    assert "auto" in decide_events[0].decision or "playbook" in decide_events[0].decision

    # 3. Stall detector test: artificially set last line time back 200s
    healing_supervisor._last_line_time[plan_id] = time.time() - 200
    stalled = healing_supervisor.check_stall(plan_id, max_idle_seconds=180)
    assert stalled is True

    feed = healing_supervisor.get_feed(plan_id)
    stall_events = [e for e in feed if "Stall Detector" in e.message]
    assert len(stall_events) >= 1


# ==============================================================================
# Chat Cancellation Test (Stop Button)
# ==============================================================================

def test_chat_cancellation_endpoint(client):
    """
    Test POST /api/chat/cancel registers the cancellation token.
    """
    session_id = "sess_cancel_test_123"
    _chat_cancellation_tokens.discard(session_id)

    res = client.post("/api/chat/cancel", json={"session_id": session_id})
    assert res.status_code == 200
    assert res.json()["status"] == "cancelled"
    assert session_id in _chat_cancellation_tokens
