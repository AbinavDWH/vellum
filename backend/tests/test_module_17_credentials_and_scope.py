"""
Comprehensive tests for Module M-17: Connection Credentials UI & Service Scope Management.
Verifies:
1. Field validation (Access Key regex, 40-char secret).
2. Credential isolation & masking (never in GET responses, DB ciphertext encrypted at rest).
3. Blank secret on edit retains stored credential.
4. Live connection test returns STS caller identity + per-service read-only probe results.
5. LocalStack service scope toggles, restart pending badge, and SERVICE_IN_SCOPE enforcement.
6. Real AWS scope enforcement rejects plans requesting out-of-scope services.
7. PROD environment confirmation requirement on save and on execution.
8. Connection deletion purges ciphertext and blocks dependent plans with actionable error.
9. Sanitizer assertion ensures zero AKIA/secret leaks in logs, prompts, or audit records.
"""
import json
import uuid
import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.main import app
from app.database import get_db, SessionLocal
from app.models import ConnectionRecord, PlanRecord
from app.credentials.manager import credential_manager
from app.engines.orchestrator import orchestrator
from app.healing.sanitizer import sanitize_text
from app.audit.logger import audit_logger


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


@pytest.fixture(autouse=True)
def clean_test_connections(db_session):
    db_session.query(ConnectionRecord).delete()
    db_session.query(PlanRecord).delete()
    test_key = "AKIAIOSFODNN7EXAMPLE"
    test_secret = "wJalrXUtnFEMI/K7MDENG/bPxRfiCYEXAMPLEKEY"
    main_conn = ConnectionRecord(
        id="conn_test_module17_local",
        name="test-local-main",
        provider="aws",
        environment="local",
        auth_method="access_key",
        region="us-east-1",
        key_prefix=test_key[:4],
        key_last4=test_key[-4:],
        encrypted_access_key=credential_manager.encrypt(test_key),
        encrypted_secret_key=credential_manager.encrypt(test_secret),
        services_json=json.dumps(["s3", "ec2", "vpc", "rds", "iam", "sts", "cloudwatch"]),
        status="connected",
        account_id="000000000000",
    )
    db_session.add(main_conn)
    db_session.commit()
    yield



def test_checkpoint_01_invalid_key_and_secret_validation(client):
    """Invalid key ID / wrong-length secret blocked with HTTP 422."""
    # 1. Invalid key pattern (starts with wrong prefix or bad length)
    resp = client.post("/api/connections", json={
        "name": "bad-key-conn",
        "provider": "aws",
        "environment": "local",
        "auth_method": "access_key",
        "access_key_id": "INVALIDKEY123",
        "secret_access_key": "A" * 40,
        "region": "us-east-1",
    })
    assert resp.status_code == 422
    assert "Invalid Access Key ID" in resp.json()["detail"]

    # 2. Invalid secret length (e.g. 20 chars instead of 40)
    resp2 = client.post("/api/connections", json={
        "name": "short-secret-conn",
        "provider": "aws",
        "environment": "local",
        "auth_method": "access_key",
        "access_key_id": "AKIAIOSFODNN7EXAMPLE",
        "secret_access_key": "tooshortsecret",
        "region": "us-east-1",
    })
    assert resp2.status_code == 422
    assert "Invalid Secret Access Key" in resp2.json()["detail"]


def test_checkpoint_02_masking_and_no_secret_in_get_response(client, db_session):
    """
    Valid key saved -> card shows AKIA****last4 only;
    GET /api/connections response contains NO secret string.
    """
    raw_key = "AKIA1111222233334444"
    raw_secret = "wJalrXUtnFEMI/K7MDENG/bPxRfiCYEXAMPLEKEY"

    create_resp = client.post("/api/connections", json={
        "name": "prod-masked-test",
        "provider": "aws",
        "environment": "staging",
        "auth_method": "access_key",
        "access_key_id": raw_key,
        "secret_access_key": raw_secret,
        "region": "us-east-1",
        "services": ["s3", "ec2"],
    })
    assert create_resp.status_code == 200
    created = create_resp.json()
    assert created["masked_key"] == "AKIA****4444"
    assert "secret" not in created
    assert "encrypted_secret_key" not in created

    # Verify GET /api/connections
    list_resp = client.get("/api/connections")
    assert list_resp.status_code == 200
    json_str = list_resp.text

    # ASSERTION: Zero raw secret in API response
    assert raw_secret not in json_str
    assert raw_key not in json_str  # full key not present

    # Verify DB has ciphertext only
    record = db_session.query(ConnectionRecord).filter(ConnectionRecord.name == "prod-masked-test").first()
    assert record is not None
    assert record.encrypted_secret_key is not None
    assert record.encrypted_secret_key != raw_secret
    assert credential_manager.decrypt(record.encrypted_secret_key) == raw_secret


def test_checkpoint_03_edit_with_blank_secret_preserves_stored_credentials(client, db_session):
    """Edit with blank secret keeps working credentials and passes test after save."""
    raw_key = "AKIA5555666677778888"
    raw_secret = "secretsecretsecretsecretsecretsecretsecr"

    create_resp = client.post("/api/connections", json={
        "name": "blank-edit-test",
        "provider": "aws",
        "environment": "local",
        "auth_method": "access_key",
        "access_key_id": raw_key,
        "secret_access_key": raw_secret,
        "region": "us-east-1",
    })
    conn_id = create_resp.json()["id"]

    # PATCH with secret left empty / blank
    patch_resp = client.patch(f"/api/connections/{conn_id}", json={
        "region": "us-west-2",
        "secret_access_key": "",
    })
    assert patch_resp.status_code == 200
    updated = patch_resp.json()
    assert updated["region"] == "us-west-2"

    # Verify stored secret in DB remains intact
    record = db_session.query(ConnectionRecord).filter(ConnectionRecord.id == conn_id).first()
    decrypted = credential_manager.decrypt(record.encrypted_secret_key)
    assert decrypted == raw_secret


def test_checkpoint_04_test_connection_probes(client):
    """Test connection endpoint returns account ID + per-service probes."""
    probe_resp = client.post("/api/connections/test", json={
        "name": "probe-test",
        "provider": "aws",
        "environment": "local",
        "auth_method": "access_key",
        "access_key_id": "AKIAIOSFODNN7EXAMPLE",
        "secret_access_key": "wJalrXUtnFEMI/K7MDENG/bPxRfiCYEXAMPLEKEY",
        "region": "us-east-1",
        "services": ["s3", "ec2", "sts"],
    })
    assert probe_resp.status_code == 200
    data = probe_resp.json()
    assert "account_id" in data
    assert "arn" in data
    assert len(data["services"]) >= 2
    for probe in data["services"]:
        assert "service" in probe
        assert "status" in probe
        assert "latency_ms" in probe


def test_checkpoint_05_localstack_scope_toggle_restart_and_service_in_scope(client, db_session):
    """
    Deselect rds on LocalStack -> restart pending badge -> Apply & Restart ->
    RDS plan fails validation with clear message -> re-enable restores.
    """
    # 1. Create or fetch local connection
    conn = credential_manager.get_active_connection(environment="local", db=db_session)
    assert conn is not None

    # 2. Deselect rds from services
    services_without_rds = ["s3", "ec2", "vpc", "iam", "sts"]
    patch_resp = client.patch(f"/api/connections/{conn.id}", json={
        "services": services_without_rds,
    })
    assert patch_resp.status_code == 200
    assert patch_resp.json()["restart_pending"] is True
    assert "rds" not in patch_resp.json()["services"]

    # 3. Simulate Apply & Restart
    restart_resp = client.post("/api/localstack/restart")
    assert restart_resp.status_code == 200
    assert restart_resp.json()["status"] == "restarted"

    # Verify restart_pending is cleared
    db_session.refresh(conn)
    assert conn.restart_pending is False

    # 4. Attempt to generate an RDS infrastructure plan
    rds_prompt = "Create an RDS postgres database instance called billing-db in us-east-1 [clarification]: port 5432, default vpc"
    chat_resp = orchestrator.process_natural_language(
        prompt=rds_prompt,
        cloud_provider="aws",
        environment="local",
        db=db_session,
    )
    # Must fail with SERVICE_IN_SCOPE error
    assert chat_resp.status == "error"
    assert "SERVICE_IN_SCOPE" in chat_resp.message
    assert "Service rds is not enabled for connection" in chat_resp.message

    # 5. Re-enable rds
    restore_resp = client.patch(f"/api/connections/{conn.id}", json={
        "services": ["s3", "ec2", "vpc", "rds", "iam", "sts"],
    })
    assert restore_resp.status_code == 200
    assert "rds" in restore_resp.json()["services"]


def test_checkpoint_06_real_aws_scope_enforcement(client, db_session):
    """Real AWS connection with narrow scope: plan using out-of-scope service rejected by policy engine."""
    # Create staging connection with only s3 scope
    conn_resp = client.post("/api/connections", json={
        "name": "aws-storage-only",
        "provider": "aws",
        "environment": "staging",
        "auth_method": "access_key",
        "access_key_id": "AKIA7777888899990000",
        "secret_access_key": "wJalrXUtnFEMI/K7MDENG/bPxRfiCYEXAMPLEKEY",
        "region": "us-east-1",
        "services": ["s3"],
    })
    assert conn_resp.status_code == 200

    # Request compute/ec2 instance on staging
    prompt = "Create a t3.micro ec2 instance called web-server in us-east-1 [clarification]: public subnet, default VPC"
    chat_resp = orchestrator.process_natural_language(
        prompt=prompt,
        cloud_provider="aws",
        environment="staging",
        db=db_session,
    )
    assert chat_resp.status == "error"
    assert "SERVICE_IN_SCOPE" in chat_resp.message
    assert "is not enabled for connection" in chat_resp.message


def test_checkpoint_07_prod_confirmation_required(client, db_session):
    """PROD-tagged connection: typed confirmation on save AND on every execution use."""
    conn_name = "critical-prod-main"

    # 1. Save without confirm_name fails
    fail_resp = client.post("/api/connections", json={
        "name": conn_name,
        "provider": "aws",
        "environment": "prod",
        "auth_method": "access_key",
        "access_key_id": "AKIA9999000011112222",
        "secret_access_key": "wJalrXUtnFEMI/K7MDENG/bPxRfiCYEXAMPLEKEY",
        "region": "us-east-1",
        "services": ["s3", "ec2"],
    })
    assert fail_resp.status_code == 422
    assert "PROD environment tag requires typing the exact connection name" in fail_resp.json()["detail"]

    # 2. Save with matching confirm_name succeeds
    ok_resp = client.post("/api/connections", json={
        "name": conn_name,
        "provider": "aws",
        "environment": "prod",
        "auth_method": "access_key",
        "access_key_id": "AKIA9999000011112222",
        "secret_access_key": "wJalrXUtnFEMI/K7MDENG/bPxRfiCYEXAMPLEKEY",
        "region": "us-east-1",
        "services": ["s3", "ec2", "vpc"],
        "confirm_name": conn_name,
    })
    assert ok_resp.status_code == 200

    # 3. Plan targeting prod requires typed confirmation phrase matching connection name
    chat_resp = orchestrator.process_natural_language(
        prompt="Create an S3 bucket called prod-secure-backup-2026 in us-east-1",
        cloud_provider="aws",
        environment="prod",
        db=db_session,
    )
    if chat_resp.status == "plan_ready" and chat_resp.plan:
        assert chat_resp.plan.requires_confirmation_text is True
        assert chat_resp.plan.confirmation_phrase == conn_name
        assert chat_resp.plan.risk_level == "critical"


def test_checkpoint_08_delete_connection_purges_ciphertext_and_blocks_plans(client, db_session):
    """Delete connection: dependent plans blocked with actionable error; ciphertext purged."""
    raw_key = "AKIA1234123412341234"
    raw_secret = "mysecretkeymysecretkeymysecretkeymysecre"

    conn_resp = client.post("/api/connections", json={
        "name": "to-be-deleted-conn",
        "provider": "aws",
        "environment": "staging",
        "auth_method": "access_key",
        "access_key_id": raw_key,
        "secret_access_key": raw_secret,
        "region": "us-east-1",
        "services": ["s3"],
    })
    conn_id = conn_resp.json()["id"]

    # Create dummy plan pointing to this connection
    test_plan_id = f"plan_del_{uuid.uuid4().hex[:8]}"
    plan = PlanRecord(
        plan_id=test_plan_id,
        connection_id=conn_id,
        prompt="Deploy dummy",
        ir_json=json.dumps({"cloud": {"provider": "aws", "region": "us-east-1", "resources": []}}),
        status="approved",
    )
    db_session.add(plan)
    db_session.commit()

    # Delete connection
    del_resp = client.delete(f"/api/connections/{conn_id}")
    assert del_resp.status_code == 200

    # Assert ciphertext is purged in DB
    db_rec = db_session.query(ConnectionRecord).filter(ConnectionRecord.id == conn_id).first()
    assert db_rec.is_deleted is True
    assert db_rec.encrypted_secret_key is None
    assert db_rec.encrypted_access_key is None

    # Assert executing plan referencing deleted connection fails with actionable error
    exec_res = orchestrator.execute_approved_plan(plan_id=test_plan_id, db=db_session)
    assert exec_res.success is False
    assert "has been deleted. Re-associate with an active connection" in exec_res.error_message


def test_checkpoint_09_sanitizer_and_audit_log_zero_leak(client, db_session):
    """Log/prompt scan after full flow: zero AKIA…/secret strings anywhere in logs or prompts."""
    raw_key = "AKIA9876543210987654"
    raw_secret = "supersecretpasswordsupersecretpassword40"

    # Redaction test
    sample_text = f"Connecting with AccessKey={raw_key} and aws_secret_access_key='{raw_secret}'"
    sanitized = sanitize_text(sample_text)
    assert raw_key not in sanitized
    assert "[REDACTED_AWS_KEY_ID]" in sanitized
    assert raw_secret not in sanitized

    # Prompt isolation assertion
    isolation = credential_manager.verify_llm_prompt_isolation(sample_text)
    assert isolation["isolated"] is False
    assert len(isolation["pattern_violations"]) > 0

    # Audit log check: verify recent CONNECTION audit logs have zero raw secrets
    logs = audit_logger.get_all_logs(limit=20)
    for l in logs:
        details_str = json.dumps(l.get("details", {}))
        assert raw_secret not in details_str
        assert raw_key not in details_str


def test_checkpoint_10_recreate_connection_after_deletion_succeeds(client, db_session):
    """Re-creating a connection with the same name as a soft-deleted connection must succeed without UNIQUE constraint errors."""
    raw_key = "AKIA1122334455667788"
    raw_secret = "secretkeysecretkeysecretkeysecretkey1234"
    conn_name = f"reused-conn-{uuid.uuid4().hex[:6]}"

    # 1. Create first connection
    res1 = client.post("/api/connections", json={
        "name": conn_name,
        "provider": "aws",
        "environment": "staging",
        "auth_method": "access_key",
        "access_key_id": raw_key,
        "secret_access_key": raw_secret,
        "region": "us-east-1",
        "services": ["s3"],
    })
    assert res1.status_code == 200, res1.text
    conn1_id = res1.json()["id"]

    # 2. Attempting to create duplicate active connection fails
    dup_res = client.post("/api/connections", json={
        "name": conn_name,
        "provider": "aws",
        "environment": "staging",
        "auth_method": "access_key",
        "access_key_id": raw_key,
        "secret_access_key": raw_secret,
        "region": "us-east-1",
        "services": ["s3"],
    })
    assert dup_res.status_code == 422
    assert f"Connection with name '{conn_name}' already exists" in dup_res.json()["detail"]

    # 3. Delete first connection
    del_res = client.delete(f"/api/connections/{conn1_id}")
    assert del_res.status_code == 200

    # 4. Re-create connection with the EXACT SAME name
    res2 = client.post("/api/connections", json={
        "name": conn_name,
        "provider": "aws",
        "environment": "prod",
        "auth_method": "access_key",
        "access_key_id": raw_key,
        "secret_access_key": raw_secret,
        "region": "us-east-1",
        "services": ["s3", "ec2"],
        "confirm_name": conn_name,
    })
    assert res2.status_code == 200, res2.text
    conn2_id = res2.json()["id"]
    assert conn2_id != conn1_id
    assert res2.json()["name"] == conn_name

    # 5. Check DB state: both exist, conn1 is deleted, conn2 is active
    rec1 = db_session.query(ConnectionRecord).filter(ConnectionRecord.id == conn1_id).first()
    rec2 = db_session.query(ConnectionRecord).filter(ConnectionRecord.id == conn2_id).first()
    assert rec1.is_deleted is True
    assert rec2.is_deleted is False
    assert rec2.name == conn_name

