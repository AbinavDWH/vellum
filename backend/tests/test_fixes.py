import json
import pytest
from fastapi.testclient import TestClient
from app.main import app
from app.models import PlanRecord, ExecutionRecord, ConnectionRecord
from app.config import settings
from app.credentials.manager import credential_manager
from app.environment.inventory import environment_inventory
from app.llm.client import llm_client
import datetime


@pytest.fixture
def client(db_session):
    return TestClient(app)


def test_execute_unapproved_plan_rejected(client, db_session):
    """Test that an unapproved plan (awaiting_approval) cannot be executed."""
    plan = PlanRecord(
        plan_id="plan_test_unapproved",
        prompt="Test unapproved plan",
        status="awaiting_approval",
        ir_json=json.dumps({"cloud": {"provider": "aws", "environment": "local"}}),
    )
    db_session.add(plan)
    db_session.commit()

    resp = client.post(f"/api/plans/{plan.plan_id}/execute")
    assert resp.status_code == 400
    assert "Only approved plans can be executed" in resp.json()["detail"]


def test_execute_halted_plan_rejected(client, db_session):
    """Test that a halted plan cannot be re-run."""
    plan = PlanRecord(
        plan_id="plan_test_halted",
        prompt="Test halted plan",
        status="halted",
        ir_json=json.dumps({"cloud": {"provider": "aws", "environment": "local"}}),
    )
    db_session.add(plan)
    db_session.commit()

    resp = client.post(f"/api/plans/{plan.plan_id}/execute")
    assert resp.status_code == 400
    assert "Halted plans cannot be re-run" in resp.json()["detail"]


def test_execute_failed_plan_prod_requires_approval(client, db_session):
    """Test that a failed plan in prod requires fresh approval."""
    plan = PlanRecord(
        plan_id="plan_test_failed_prod",
        prompt="Test failed prod plan",
        status="failed",
        ir_json=json.dumps({"cloud": {"provider": "aws", "environment": "prod"}}),
    )
    db_session.add(plan)
    db_session.commit()

    resp = client.post(f"/api/plans/{plan.plan_id}/execute")
    assert resp.status_code == 400
    assert "require a new human approval" in resp.json()["detail"]


def test_executions_history_completed_at(client, db_session):
    """Test that list_executions and list_plan_executions compute completed_at dynamically without crashing."""
    plan = PlanRecord(
        plan_id="plan_test_history",
        prompt="Test history",
        status="completed",
        ir_json=json.dumps({"cloud": {"provider": "aws", "environment": "local"}}),
    )
    db_session.add(plan)
    db_session.commit()

    started = datetime.datetime(2026, 10, 8, 12, 0, 0)
    exec_rec = ExecutionRecord(
        plan_id=plan.plan_id,
        status="completed",
        success=True,
        started_at=started,
        duration_seconds=15.5,
    )
    db_session.add(exec_rec)
    db_session.commit()

    resp = client.get("/api/executions")
    assert resp.status_code == 200
    items = resp.json()
    match = [i for i in items if i["plan_id"] == plan.plan_id]
    assert len(match) == 1
    assert match[0]["started_at"] is not None
    assert match[0]["completed_at"] is not None
    assert "2026-10-08T12:00:15.500000" in match[0]["completed_at"]

    resp_plan = client.get(f"/api/plans/{plan.plan_id}/executions")
    assert resp_plan.status_code == 200
    items_plan = resp_plan.json()
    assert len(items_plan) == 1
    assert items_plan[0]["completed_at"] is not None


def test_rollback_missing_terraform_returns_error(client, db_session, monkeypatch):
    """Test that rollback returns a clear 400 error when terraform binary is not found."""
    plan = PlanRecord(
        plan_id="plan_test_rollback_no_tf",
        prompt="Test rollback without terraform",
        status="approved",
        ir_json=json.dumps({"cloud": {"provider": "aws", "environment": "local"}}),
    )
    db_session.add(plan)
    db_session.commit()

    from app.engines.execution_engine import execution_engine
    monkeypatch.setattr(execution_engine, "terraform_binary", "nonexistent_tf_bin_123")

    resp = client.post(f"/api/plans/{plan.plan_id}/rollback")
    assert resp.status_code == 400
    assert "not found" in resp.json()["detail"].lower()


def test_restart_localstack_reports_failure_when_docker_fails(client, db_session, monkeypatch):
    """Test that restart_localstack reports failure and does not mark connections as connected when container is down."""
    conn = ConnectionRecord(
        id="conn_local_test",
        name="LocalStack Test",
        provider="aws",
        environment="local",
        status="disconnected",
        is_deleted=False,
    )
    db_session.add(conn)
    db_session.commit()

    res = credential_manager.restart_localstack(db_session)
    assert res["status"] == "failed"
    assert "failed" in res["message"].lower()

    db_session.refresh(conn)
    assert conn.status == "error"


def test_switch_ai_to_groq_without_key_refused(client):
    """Test that switching to Groq with no API key is refused with a 400 error."""
    original_key = llm_client.groq.api_key
    try:
        llm_client.groq.api_key = None
        resp = client.post("/api/ai/active", json={"provider": "groq"})
        assert resp.status_code == 400
        assert "GROQ_API_KEY is not configured" in resp.json()["detail"]
    finally:
        llm_client.groq.api_key = original_key


def test_environment_snapshot_unavailable_flag(client):
    """Test that environment snapshot includes unavailable flag when LocalStack is down."""
    resp = client.get("/api/environment/snapshot?environment=local")
    assert resp.status_code == 200
    data = resp.json()
    assert "unavailable" in data
    # Since LocalStack container is not running on port 4566, unavailable must be True
    assert data["unavailable"] is True


def test_connection_test_does_not_show_fake_account_id_on_error(client, db_session):
    """Test that connection test does not return fake 000000000000 account id for unverified keys."""
    res = credential_manager.probe_connection(
        provider="aws",
        environment="prod",
        access_key="AKIAFAKEKEYEXAMPLE",
        secret_key="FAKE_SECRET_KEY_NOT_REAL",
    )
    assert res["overall_status"] == "error"
    assert res["account_id"] is None
    assert res["arn"] is None


def test_scope_fidelity_nat_gateway_and_elastic_ip():
    """Test that nat_gateway and elastic_ip do not trigger SCOPE_FIDELITY violations."""
    from app.validation.scope_fidelity import ScopeFidelityValidator
    from app.schemas.ir import UniversalIR
    from app.schemas.cloud import CloudPlan, CloudResource

    prompt = (
        "Synthesize complete infrastructure plan based on the documented requirements specification:\n\n"
        "# Spec\n- **Cloud Provider**: AWS\n- **Environment**: prod\n\n"
        "## Resources\n- vpc: cidr=10.0.0.0/16\n- subnet: az=us-east-1a\n- nat_gateway: requested=true\n\n"
        "## Notes\n- Subnet tiering: public only\n- Subnet CIDR not provided"
    )
    ir = UniversalIR(
        intent="deploy_cloud",
        cloud=CloudPlan(
            provider="aws",
            environment="prod",
            resources=[
                CloudResource(name="main_vpc", type="vpc", properties={"cidr_block": "10.0.0.0/16"}),
                CloudResource(name="public_subnet_1", type="subnet", properties={"cidr_block": "10.0.1.0/24", "public": True}),
                CloudResource(name="nat_gw", type="nat_gateway", properties={"subnet_name": "public_subnet_1"}),
                CloudResource(name="nat_eip", type="elastic_ip", properties={}),
            ]
        )
    )

    is_valid, errors, annotated_ir = ScopeFidelityValidator.validate(prompt, ir)
    assert is_valid, f"Expected valid, got errors: {errors}"
    assert len(errors) == 0

    # Ensure elastic_ip was annotated as a technical dependency of nat_gateway
    eip_res = next(r for r in annotated_ir.cloud.resources if r.type == "elastic_ip")
    assert eip_res.is_dependency is True
    assert "NAT Gateway" in eip_res.dependency_reason


def test_aws_adapter_terraform_nat_gateway_and_elastic_ip():
    """Test that AWS adapter generates correct Terraform for NAT Gateway and Elastic IP."""
    from app.adapters.cloud.aws import AWSAdapter
    from app.schemas.ir import UniversalIR
    from app.schemas.cloud import CloudPlan, CloudResource

    adapter = AWSAdapter()
    ir = UniversalIR(
        intent="deploy_cloud",
        cloud=CloudPlan(
            provider="aws",
            environment="prod",
            resources=[
                CloudResource(name="main_vpc", type="vpc", properties={"cidr_block": "10.0.0.0/16"}),
                CloudResource(name="public_subnet_1", type="subnet", properties={"cidr_block": "10.0.1.0/24", "public": True}),
                CloudResource(name="nat_gw", type="nat_gateway", properties={"subnet_name": "public_subnet_1"}),
                CloudResource(name="nat_eip", type="elastic_ip", properties={}),
            ]
        )
    )

    tf_code = adapter.generate_terraform(ir, environment="prod")
    assert 'resource "aws_eip" "nat_eip"' in tf_code
    assert 'resource "aws_nat_gateway" "nat_gw"' in tf_code
    assert 'allocation_id = aws_eip.nat_eip.id' in tf_code
    assert 'subnet_id     = aws_subnet.public_subnet_1.id' in tf_code

