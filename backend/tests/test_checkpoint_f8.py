import pytest
from fastapi.testclient import TestClient
from app.main import app
from app.models import PlanRecord, ExecutionRecord
from app.database import SessionLocal


client = TestClient(app)


def test_f8_chat_stop_endpoint():
    """Checkpoint F8: POST /api/chat/stop/{session_id} stops in-flight chat."""
    resp = client.post("/api/chat/stop/session_f8_test")
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "stopped"
    assert data["session_id"] == "session_f8_test"


def test_f8_terminate_execution_by_id_endpoints():
    """Checkpoint F8: POST /api/executions/{id}/terminate supports graceful (SIGINT) and force (SIGKILL)."""
    db = SessionLocal()
    try:
        # Create test plan and execution
        plan_rec = PlanRecord(
            plan_id="plan_f8_terminate_test",
            prompt="test prompt",
            intent="deploy_cloud",
            risk_level="low",
            status="running",
            ir_json='{"intent": "deploy_cloud"}',
            terraform_code="",
        )
        db.add(plan_rec)
        db.commit()

        exec_rec = ExecutionRecord(
            plan_id="plan_f8_terminate_test",
            run_number=1,
            status="running",
            resources_created=0,
            resources_updated=0,
            resources_deleted=0,
            duration_seconds=0.0,
        )
        db.add(exec_rec)
        db.commit()
        db.refresh(exec_rec)

        # 1. Click 1: Graceful stop via execution ID
        resp1 = client.post(f"/api/executions/{exec_rec.id}/terminate", json={"force": False})
        assert resp1.status_code == 200
        data1 = resp1.json()
        assert data1["mode"] == "sigint"

        # 2. Click 2: Force kill via execution ID
        resp2 = client.post(f"/api/executions/{exec_rec.id}/terminate", json={"force": True})
        assert resp2.status_code == 200
        data2 = resp2.json()
        assert data2["mode"] == "sigkill"

        # 3. Terminate via plan ID
        resp3 = client.post(f"/api/executions/plan_f8_terminate_test/terminate", json={"force": False})
        assert resp3.status_code == 200
        assert resp3.json()["mode"] == "sigint"

    finally:
        db.close()
