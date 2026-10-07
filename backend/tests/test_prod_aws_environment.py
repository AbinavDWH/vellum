import os
import pytest
from app.adapters.cloud.aws import AWSAdapter
from app.engines.orchestrator import orchestrator
from app.engines.execution_engine import execution_engine
from app.environment.inventory import environment_inventory
from app.requirements import requirements_manager
from app.database import init_db, SessionLocal
from app.models import SessionRecord, PlanRecord, ConnectionRecord
from app.schemas.ir import UniversalIR


@pytest.fixture(autouse=True)
def setup_db():
    init_db()
    db = SessionLocal()
    yield db
    db.close()


def test_aws_adapter_prod_vs_local_terraform():
    """Verify AWSAdapter differentiates between local (LocalStack) and prod (real AWS)."""
    adapter = AWSAdapter()
    mapped = [
        {
            "tf_type": "aws_s3_bucket",
            "name": "prod_data_bucket",
            "properties": {"bucket_name": "prod-data-bucket-12345"},
            "tags": {"Environment": "prod"},
        }
    ]

    # 1. Local environment
    local_tf = adapter.generate_terraform(mapped, environment="local")
    assert 'access_key                  = "test"' in local_tf
    assert 'secret_key                  = "test"' in local_tf
    assert "endpoints {" in local_tf
    assert "s3_use_path_style           = true" in local_tf

    # 2. Production environment
    prod_tf = adapter.generate_terraform(mapped, environment="prod", region="us-west-2")
    assert 'access_key' not in prod_tf
    assert 'secret_key' not in prod_tf
    assert "endpoints {" not in prod_tf
    assert "s3_use_path_style" not in prod_tf
    assert 'region = "us-west-2"' in prod_tf
    assert 'resource "aws_s3_bucket" "prod_data_bucket"' in prod_tf


def test_orchestrator_environment_retention(setup_db):
    """Verify orchestrator retains and respects prod environment in living requirements."""
    import uuid
    db = setup_db
    session_id = f"sess_prod_{uuid.uuid4().hex[:8]}"

    # Start with prod environment
    res = orchestrator.process_natural_language(
        prompt="Let's design a high availability S3 storage system for production analytics",
        cloud_provider="aws",
        environment="prod",
        session_id=session_id,
        db=db,
    )
    assert res.requirements_md is not None
    assert "- **Environment**: prod" in res.requirements_md

    # Even if plan_from_requirements is triggered without explicit env argument,
    # it must read and preserve prod from the living requirements specification
    plan_res = orchestrator.plan_from_requirements(
        session_id=session_id,
        cloud_provider="aws",
        environment="local",  # Deliberately pass local fallback
        db=db,
    )
    assert plan_res.status in ["plan_ready", "clarification_needed"]
    if plan_res.plan:
        plan_rec = db.query(PlanRecord).filter(PlanRecord.plan_id == plan_res.plan.plan_id).first()
        assert plan_rec is not None
        assert "access_key = \"test\"" not in plan_rec.terraform_code


def test_inventory_get_snapshot_prod_does_not_use_localstack():
    """Verify inventory scanner uses real AWS client configuration when environment is prod."""
    client = environment_inventory._get_boto3_client("s3", region="us-east-1", environment="prod")
    # Verify endpoint_url is not LocalStack (boto3 client meta.endpoint_url)
    assert "localhost:4566" not in client.meta.endpoint_url
    assert "127.0.0.1:4566" not in client.meta.endpoint_url


def test_execution_engine_prod_no_localstack_simulation(setup_db, monkeypatch):
    """Verify execution engine does not enter LocalStack simulation mode for prod plans."""
    import uuid
    db = setup_db
    plan_id = f"plan_prod_mock_{uuid.uuid4().hex[:8]}"

    # Ensure LocalStack is reported as offline
    monkeypatch.setattr(execution_engine, "is_localstack_online", lambda: False)

    # Mock terraform execution so we don't actually deploy live AWS resources in test
    captured_logs = []

    def mock_subprocess_run(cmd, *args, **kwargs):
        class Result:
            returncode = 0
            stdout = "Apply complete! Resources: 1 added, 0 changed, 0 destroyed."
            stderr = ""
        return Result()

    import subprocess
    monkeypatch.setattr(subprocess, "run", mock_subprocess_run)

    # Create dummy workspace with main.tf
    ws_dir = f"/tmp/vellum_test_workspace/{plan_id}"
    os.makedirs(ws_dir, exist_ok=True)
    with open(f"{ws_dir}/main.tf", "w") as f:
        f.write('resource "aws_s3_bucket" "test_prod" { bucket = "my-prod-test-bucket" }\n')

    plan = PlanRecord(
        plan_id=plan_id,
        prompt="Deploy S3 bucket in prod",
        intent="CREATE_STORAGE",
        risk_level="high",
        status="approved",
        ir_json='{"cloud": {"provider": "aws", "environment": "prod", "region": "us-east-1", "resources": []}}',
        terraform_code='resource "aws_s3_bucket" "test_prod" { bucket = "my-prod-test-bucket" }',
    )
    db.add(plan)
    db.commit()

    exec_res = execution_engine.execute_plan(
        plan_dir=ws_dir,
        plan_id=plan_id,
        on_log=lambda m: captured_logs.append(m),
        db=db,
    )

    assert exec_res.success is True
    # Must NOT have logged "LocalStack container is not running on port 4566. Executing in validated simulation mode"
    assert not any("LocalStack container is not running" in log for log in captured_logs)
    assert not any("Executing in validated simulation mode" in log for log in captured_logs)
    assert any("Target environment: AWS PROD" in log for log in captured_logs)


def test_prod_connection_creation_deletion_and_recreation(setup_db):
    """Verify creating a prod connection, deleting it, and recreating with identical name succeeds."""
    import uuid
    from app.credentials.manager import credential_manager
    db = setup_db
    conn_name = f"test_conn_{uuid.uuid4().hex[:6]}"
    ak = "AKIA1234567890123456"
    sk = "1234567890123456789012345678901234567890"

    # 1. Create connection
    c1 = credential_manager.create_connection(
        db=db,
        name=conn_name,
        provider="aws",
        environment="prod",
        auth_method="access_key",
        region="us-east-1",
        access_key_id=ak,
        secret_access_key=sk,
        confirm_name=conn_name,
    )
    assert c1["name"] == conn_name
    assert c1["environment"] == "prod"

    # 2. Delete connection
    del_res = credential_manager.delete_connection(db, c1["id"])
    assert del_res["deleted"] is True

    # 3. Re-create connection with same name
    c2 = credential_manager.create_connection(
        db=db,
        name=conn_name,
        provider="aws",
        environment="prod",
        auth_method="access_key",
        region="us-east-1",
        access_key_id=ak,
        secret_access_key=sk,
        confirm_name=conn_name,
    )
    assert c2["name"] == conn_name
    assert c2["id"] != c1["id"]

    # 4. Active connections list only contains active one
    active_conns = credential_manager.list_connections(db)
    matches = [c for c in active_conns if c["name"] == conn_name]
    assert len(matches) == 1
    assert matches[0]["id"] == c2["id"]

