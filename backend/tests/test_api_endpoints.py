import json
import pytest
from fastapi.testclient import TestClient
from app.main import app
from app.database import SessionLocal
from app.models import PlanRecord
from app.schemas.ir import UniversalIR
from app.schemas.cloud import CloudPlan, CloudResource
from app.engines.terraform_generator import tf_generator


@pytest.fixture
def client():
    return TestClient(app)


@pytest.fixture
def sample_approved_plan():
    db = SessionLocal()
    plan_id = "test_api_plan_001"
    
    # Clean up existing record if any
    existing = db.query(PlanRecord).filter(PlanRecord.plan_id == plan_id).first()
    if existing:
        db.delete(existing)
        db.commit()

    sample_ir = UniversalIR(
        intent="deploy_cloud",
        cloud=CloudPlan(
            provider="aws",
            region="us-east-1",
            environment="local",
            resources=[
                CloudResource(
                    type="object_storage",
                    name="test-api-bucket",
                    properties={"bucket_name": "test-api-bucket"},
                )
            ],
        ),
    )

    plan_dir = tf_generator.generate(sample_ir, environment="local", plan_id=plan_id)
    with open(f"{plan_dir}/main.tf", "r") as f:
        tf_code = f.read()

    record = PlanRecord(
        plan_id=plan_id,
        prompt="Deploy an S3 bucket for API testing",
        intent="deploy_cloud",
        risk_level="low",
        status="approved",
        ir_json=json.dumps(sample_ir.model_dump()),
        terraform_code=tf_code,
        requires_confirmation_text=False,
    )
    db.add(record)
    db.commit()
    db.close()

    yield plan_id

    # Teardown
    db = SessionLocal()
    rec = db.query(PlanRecord).filter(PlanRecord.plan_id == plan_id).first()
    if rec:
        db.delete(rec)
        db.commit()
    db.close()


def test_health_endpoint(client):
    res = client.get("/api/health")
    assert res.status_code == 200
    data = res.json()
    assert data["status"] == "healthy"
    assert data["service"] == "Vellum"


def test_models_endpoint(client):
    res = client.get("/api/models")
    assert res.status_code == 200
    data = res.json()
    assert isinstance(data, list)
    assert len(data) > 0
    assert "id" in data[0]


def test_plans_list_and_details(client, sample_approved_plan):
    res = client.get("/api/plans")
    assert res.status_code == 200
    plans = res.json()
    assert isinstance(plans, list)
    assert any(p["plan_id"] == sample_approved_plan for p in plans)

    res_details = client.get(f"/api/plans/{sample_approved_plan}")
    assert res_details.status_code == 200
    detail = res_details.json()
    assert detail["plan_id"] == sample_approved_plan
    assert detail["status"] == "approved"
    assert "ir" in detail
    assert "generated_terraform" in detail


def test_websocket_execution_and_replay(client, sample_approved_plan):
    # 1. Connect to live WebSocket stream
    received_logs = []
    completed_msg = None

    with client.websocket_connect(f"/ws/execution/{sample_approved_plan}") as ws:
        while True:
            text = ws.receive_text()
            if text.startswith("__COMPLETED__"):
                completed_msg = text
                break
            elif text.startswith("__ERROR__"):
                pytest.fail(f"WebSocket execution reported error: {text}")
            else:
                received_logs.append(text)

    assert len(received_logs) > 0
    assert completed_msg is not None
    res_data = json.loads(completed_msg.replace("__COMPLETED__", ""))
    assert res_data["status"] == "completed"
    assert res_data["success"] is True

    # 2. Re-connecting to a completed plan replays logs and finishes with __COMPLETED__
    replay_logs = []
    replay_completed = None
    with client.websocket_connect(f"/ws/execution/{sample_approved_plan}") as ws:
        while True:
            text = ws.receive_text()
            if text.startswith("__COMPLETED__"):
                replay_completed = text
                break
            else:
                replay_logs.append(text)

    assert replay_completed is not None
    replay_data = json.loads(replay_completed.replace("__COMPLETED__", ""))
    assert replay_data["status"] == "completed"
    assert replay_data["success"] is True

    # 3. REST execute fallback on an already completed plan returns completed result without error 400
    rest_res = client.post(f"/api/plans/{sample_approved_plan}/execute")
    assert rest_res.status_code == 200
    rest_data = rest_res.json()
    assert rest_data["status"] == "completed"
    assert rest_data["success"] is True


def test_verification_endpoint(client, sample_approved_plan):
    res = client.post(f"/api/plans/{sample_approved_plan}/verify")
    assert res.status_code == 200
    report = res.json()
    assert report["plan_id"] == sample_approved_plan
    assert "drift_detected" in report
    assert "resources_verified" in report


def test_audit_endpoint(client):
    res = client.get("/api/audit")
    assert res.status_code == 200
    logs = res.json()
    assert isinstance(logs, list)
    assert len(logs) > 0
    assert "event_type" in logs[0]


def test_environment_snapshot_and_rescan_endpoints(client):
    # 1. Snapshot endpoint
    res = client.get("/api/environment/snapshot")
    assert res.status_code == 200
    data = res.json()
    assert "snapshot_id" in data
    assert "snapshot_hash" in data
    assert "counts" in data
    assert "buckets" in data["counts"]

    # 2. Rescan endpoint
    rescan = client.post("/api/environment/rescan")
    assert rescan.status_code == 200
    r_data = rescan.json()
    assert r_data["status"] == "rescanned"
    assert "snapshot_hash" in r_data
    assert "counts" in r_data
