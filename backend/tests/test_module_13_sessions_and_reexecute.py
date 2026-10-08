"""
Test suite for Module M-13: Chat Session Memory & Plan Re-Execution.
Verifies:
1. Sessions CRUD (create, list, get, rename, soft-delete with audit).
2. Messages write-through on chat.
3. Safety-first re-execution flow:
   - No-op on unchanged infrastructure (REEXEC_NOOP).
   - Drift detection requires fresh human approval (REEXEC_DRIFT_DETECTED, REEXEC_REQUESTED).
   - Approval records REEXEC_APPROVED and increments run_number (run #2).
4. Idempotency key deduplication.
"""
import pytest
import json
from fastapi.testclient import TestClient
from app.main import app
from app.database import SessionLocal
from app.models import PlanRecord, ExecutionRecord, SessionRecord, MessageRecord, AuditLogRecord
from app.schemas.ir import UniversalIR

client = TestClient(app)


@pytest.fixture
def clean_db():
    db = SessionLocal()
    test_ids = ["plan_reexec_noop_test", "plan_reexec_drift_test", "plan_idem_cache_test"]
    db.query(ExecutionRecord).filter(ExecutionRecord.plan_id.in_(test_ids)).delete(synchronize_session=False)
    db.query(AuditLogRecord).filter(AuditLogRecord.plan_id.in_(test_ids)).delete(synchronize_session=False)
    db.query(PlanRecord).filter(PlanRecord.plan_id.in_(test_ids)).delete(synchronize_session=False)
    db.commit()
    try:
        yield db
    finally:
        db.query(ExecutionRecord).filter(ExecutionRecord.plan_id.in_(test_ids)).delete(synchronize_session=False)
        db.query(AuditLogRecord).filter(AuditLogRecord.plan_id.in_(test_ids)).delete(synchronize_session=False)
        db.query(PlanRecord).filter(PlanRecord.plan_id.in_(test_ids)).delete(synchronize_session=False)
        db.commit()
        db.close()


def test_sessions_crud(clean_db):
    """Test session creation, listing, renaming, and soft-delete."""
    # 1. Create session
    create_res = client.post("/api/sessions", json={"title": "Test VPC Architecture"})
    assert create_res.status_code == 200
    session_data = create_res.json()
    session_id = session_data["id"]
    assert session_data["title"] == "Test VPC Architecture"
    assert session_data["status"] == "active"
    assert session_data["message_count"] == 0

    # 2. List sessions
    list_res = client.get("/api/sessions")
    assert list_res.status_code == 200
    sessions = list_res.json()
    assert any(s["id"] == session_id for s in sessions)

    # 3. Rename session
    patch_res = client.patch(f"/api/sessions/{session_id}", json={"title": "Renamed Production VPC"})
    assert patch_res.status_code == 200
    assert patch_res.json()["title"] == "Renamed Production VPC"

    # 4. Get session details
    get_res = client.get(f"/api/sessions/{session_id}")
    assert get_res.status_code == 200
    assert get_res.json()["title"] == "Renamed Production VPC"

    # 5. Soft-delete session
    del_res = client.delete(f"/api/sessions/{session_id}")
    assert del_res.status_code == 200
    assert del_res.json()["status"] == "deleted"

    # Verify session is excluded from active list
    list_after_del = client.get("/api/sessions").json()
    assert not any(s["id"] == session_id for s in list_after_del)

    # Verify audit record was created for session deletion (Rule 2)
    audit_rec = clean_db.query(AuditLogRecord).filter(AuditLogRecord.event_type == "SESSION_DELETED").order_by(AuditLogRecord.id.desc()).first()
    assert audit_rec is not None
    assert session_id in audit_rec.details_json


from unittest.mock import patch
from app.schemas.api import ChatResponse


def test_chat_write_through_session(clean_db):
    """Test that chat turns write through to sessions and messages."""
    import uuid
    session_id = f"sess_test_{uuid.uuid4().hex[:8]}"

    # Mock chat payload
    chat_payload = {
        "prompt": "Create an S3 assets bucket with versioning on AWS",
        "session_id": session_id,
        "cloud_provider": "aws",
        "environment": "local"
    }

    mock_response = ChatResponse(
        status="plan_ready",
        message="Created plan for S3 assets bucket",
        plan=None,
    )

    with patch("app.main.orchestrator.process_natural_language", return_value=mock_response):
        res = client.post("/api/chat", json=chat_payload)
        assert res.status_code == 200

    # Verify session was created and auto-titled from first prompt
    session = clean_db.query(SessionRecord).filter(SessionRecord.id == session_id).first()
    assert session is not None
    assert "S3 assets bucket" in session.title
    assert session.message_count >= 2

    # Verify messages are in messages table
    messages_res = client.get(f"/api/sessions/{session_id}/messages")
    assert messages_res.status_code == 200
    messages = messages_res.json()
    assert len(messages) >= 2
    assert messages[0]["role"] == "user"
    assert "S3 assets bucket" in messages[0]["content"]
    assert messages[1]["role"] == "assistant"


def test_reexecute_flow_noop(clean_db):
    """Test re-execute on unchanged infrastructure returns no-op without re-executing."""
    plan_id = "plan_reexec_noop_test"

    # Seed completed plan and initial execution (run #1)
    ir = UniversalIR(
        intent="deploy_cloud",
        cloud={
            "provider": "aws",
            "region": "us-east-1",
            "environment": "local",
            "resources": []
        }
    )

    plan = PlanRecord(
        plan_id=plan_id,
        prompt="Test noop reexecute",
        status="completed",
        ir_json=json.dumps(ir.model_dump()),
        risk_level="low",
    )
    clean_db.add(plan)

    initial_exec = ExecutionRecord(
        plan_id=plan_id,
        run_number=1,
        status="completed",
        success=True,
    )
    clean_db.add(initial_exec)
    clean_db.commit()

    # Re-execute against unchanged infrastructure (empty resources = matches)
    reexec_res = client.post(f"/api/plans/{plan_id}/re-execute", json={"idempotency_key": "idem-noop-123"})
    assert reexec_res.status_code == 200
    data = reexec_res.json()
    assert data["status"] == "noop"
    assert data["has_changes"] is False
    assert "matches plan" in data["message"].lower()

    # Verify NO new execution was created
    runs_count = clean_db.query(ExecutionRecord).filter(ExecutionRecord.plan_id == plan_id).count()
    assert runs_count == 1

    # Verify REEXEC_NOOP audit log exists
    audit = clean_db.query(AuditLogRecord).filter(
        AuditLogRecord.plan_id == plan_id,
        AuditLogRecord.event_type == "REEXEC_NOOP"
    ).first()
    assert audit is not None


def test_reexecute_flow_drift_requires_fresh_approval(clean_db):
    """Test re-execute with detected drift requires fresh human approval and creates run #2."""
    plan_id = "plan_reexec_drift_test"

    # Seed completed plan expecting an S3 bucket
    ir = UniversalIR(
        intent="deploy_cloud",
        cloud={
            "provider": "aws",
            "region": "us-east-1",
            "environment": "local",
            "resources": [
                {
                    "type": "object_storage",
                    "name": "vellum_missing_bucket_99",
                    "properties": {"bucket_name": "vellum-missing-bucket-99"}
                }
            ]
        }
    )

    plan = PlanRecord(
        plan_id=plan_id,
        prompt="Deploy bucket 99",
        status="completed",
        ir_json=json.dumps(ir.model_dump()),
        risk_level="low",
    )
    clean_db.add(plan)

    initial_exec = ExecutionRecord(
        plan_id=plan_id,
        run_number=1,
        status="completed",
        success=True,
    )
    clean_db.add(initial_exec)
    clean_db.commit()

    # 1. Re-execute triggers dry-run and detects drift (missing bucket)
    from unittest.mock import patch
    from app.engines.verification_engine import verification_engine

    mock_drift = {
        "status": "drift_detected",
        "drift_detected": True,
        "resources_verified": 0,
        "missing_resources": ["vellum_missing_bucket_99"],
        "unexpected_resources": [],
        "modified_resources": [],
    }
    with patch.object(verification_engine, "verify", return_value=mock_drift):
        reexec_res = client.post(f"/api/plans/{plan_id}/re-execute")

    assert reexec_res.status_code == 200
    data = reexec_res.json()

    assert data["status"] == "drift_detected"
    assert data["has_changes"] is True
    assert "vellum_missing_bucket_99" in data["diff"]["missing"]
    assert data["requires_confirmation_text"] is True

    # Plan status must be reset to awaiting_approval
    plan_updated = clean_db.query(PlanRecord).filter(PlanRecord.plan_id == plan_id).first()
    assert plan_updated.status == "awaiting_approval"

    # 2. Fresh approval submitted by human operator
    approval_res = client.post(
        f"/api/plans/{plan_id}/approval",
        json={
            "decision": "approve",
            "confirmation_text": data["confirmation_phrase"]
        }
    )
    assert approval_res.status_code == 200
    assert approval_res.json()["status"] == "approved"

    # Verify REEXEC_APPROVED audit log was created
    audit_approval = clean_db.query(AuditLogRecord).filter(
        AuditLogRecord.plan_id == plan_id,
        AuditLogRecord.event_type == "REEXEC_APPROVED"
    ).first()
    assert audit_approval is not None

    # 3. Execution of approved plan creates Run #2
    exec_res = client.post(f"/api/plans/{plan_id}/execute")
    assert exec_res.status_code == 200
    exec_data = exec_res.json()
    assert exec_data["run_number"] == 2

    # Verify executions count is now 2
    runs = clean_db.query(ExecutionRecord).filter(ExecutionRecord.plan_id == plan_id).order_by(ExecutionRecord.run_number.asc()).all()
    assert len(runs) == 2
    assert runs[0].run_number == 1
    assert runs[1].run_number == 2


def test_reexecute_idempotency_cache(clean_db):
    """Test duplicate re-execute requests return cached result."""
    plan_id = "plan_idem_cache_test"

    ir = UniversalIR(
        intent="deploy_cloud",
        cloud={"provider": "aws", "region": "us-east-1", "environment": "local", "resources": []}
    )
    plan = PlanRecord(
        plan_id=plan_id,
        prompt="Idem test",
        status="completed",
        ir_json=json.dumps(ir.model_dump()),
        risk_level="low",
    )
    clean_db.add(plan)
    clean_db.commit()

    key = "idem-test-key-555"

    res1 = client.post(f"/api/plans/{plan_id}/re-execute", json={"idempotency_key": key})
    assert res1.status_code == 200

    # Second identical call should hit idempotency cache
    res2 = client.post(f"/api/plans/{plan_id}/re-execute", json={"idempotency_key": key})
    assert res2.status_code == 200
    assert res2.json()["status"] == res1.json()["status"]
