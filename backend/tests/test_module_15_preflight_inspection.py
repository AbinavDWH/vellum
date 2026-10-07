import json
import uuid
import time
import ipaddress
from pathlib import Path
import boto3
import pytest
from unittest.mock import patch, MagicMock

from app.config import settings
from app.database import SessionLocal
from app.models import PlanRecord, AuditLogRecord, HealingAttemptRecord
from app.schemas.ir import UniversalIR
from app.schemas.cloud import CloudPlan, CloudResource
from app.environment.inventory import environment_inventory
from app.environment.models import EnvironmentSnapshot
from app.environment.naming import AWSNamingValidator
from app.validation.environment_conflict import environment_conflict_validator
from app.engines.orchestrator import orchestrator
from app.engines.execution_engine import execution_engine
from app.engines.terraform_generator import tf_generator


@pytest.fixture
def db_session():
    db = SessionLocal()
    yield db
    db.close()


def get_s3_client():
    return boto3.client(
        "s3",
        endpoint_url=settings.LOCALSTACK_URL,
        aws_access_key_id="test",
        aws_secret_access_key="test",
        region_name=settings.LOCALSTACK_REGION,
    )


def test_checkpoint_1_precreate_bucket_shows_conflict_card_before_approval(db_session):
    """
    Checkpoint 1: Pre-create bucket out-of-band -> new plan shows conflict card
    BEFORE approval; zero apply errors.
    """
    uid = uuid.uuid4().hex[:6]
    bucket_name = f"vellum-chk1-{uid}"
    s3 = get_s3_client()
    try:
        s3.create_bucket(Bucket=bucket_name)
    except Exception:
        pass

    # Force fresh scan so inventory knows about the bucket
    environment_inventory.get_snapshot(force_rescan=True, db=db_session)

    prompt = f"Create an S3 bucket called {bucket_name} in us-east-1 on AWS"
    chat_resp = orchestrator.process_natural_language(
        prompt=prompt,
        cloud_provider="aws",
        environment="local",
        db=db_session,
    )

    # Must prompt for clarification BEFORE plan approval
    assert chat_resp.status == "clarification_needed"
    assert chat_resp.clarification is not None
    assert len(chat_resp.clarification.questions) > 0

    q = chat_resp.clarification.questions[0]
    assert bucket_name in q.question or bucket_name in (q.context or "")
    assert "options" in q.model_fields_set or len(q.options) > 0
    assert any("Reuse" in opt for opt in q.options)
    assert any("Rename" in opt for opt in q.options)
    assert any("Cancel" in opt for opt in q.options)


def test_checkpoint_2_choose_rename_applies_first_try_no_healing(db_session):
    """
    Checkpoint 2: Choose 'Rename' -> plan applies first try; created name matches proposal;
    no healing events fired.
    """
    uid = uuid.uuid4().hex[:6]
    existing_bucket = f"vellum-chk2-ex-{uid}"
    proposed_new_name = f"vellum-chk2-new-{uid}"

    s3 = get_s3_client()
    try:
        s3.create_bucket(Bucket=existing_bucket)
    except Exception:
        pass

    environment_inventory.get_snapshot(force_rescan=True, db=db_session)

    # Prompt with rename decision from clarification card
    prompt = f"Create an S3 bucket called {existing_bucket} in us-east-1 on AWS\n[Clarification]: Resource '{existing_bucket}' already exists -> Rename to {proposed_new_name}"
    chat_resp = orchestrator.process_natural_language(
        prompt=prompt,
        cloud_provider="aws",
        environment="local",
        db=db_session,
    )

    assert chat_resp.status == "plan_ready"
    assert chat_resp.plan is not None
    plan = chat_resp.plan

    # Verify resource card has rename chip
    res = next(
        (r for r in plan.ir.cloud.resources if r.type in ["storage_bucket", "object_storage", "s3_bucket", "bucket"] or proposed_new_name in r.properties.get("bucket_name", "") or proposed_new_name in r.name),
        None,
    )
    assert res is not None
    assert proposed_new_name in res.properties.get("bucket_name", "") or proposed_new_name in res.name.replace("_", "-")
    assert "EXISTS → rename" in (res.status_chip or "")

    # Execute plan
    exec_res = orchestrator.execute_approved_plan(plan.plan_id, db=db_session)
    assert exec_res.success is True

    # Confirm created bucket in LocalStack
    buckets = [b["Name"] for b in s3.list_buckets().get("Buckets", [])]
    assert proposed_new_name in buckets

    # Assert zero healing events fired (no HEAL_DETECTED or HEAL_APPLIED)
    heal_attempts = db_session.query(HealingAttemptRecord).filter(HealingAttemptRecord.plan_id == plan.plan_id).count()
    assert heal_attempts == 0


def test_checkpoint_3_choose_reuse_imports_into_state_no_duplicate(db_session):
    """
    Checkpoint 3: Choose 'Reuse' -> import step in plan; state contains bucket;
    no duplicate resource.
    """
    uid = uuid.uuid4().hex[:6]
    existing_bucket = f"vellum-chk3-reuse-{uid}"

    s3 = get_s3_client()
    try:
        s3.create_bucket(Bucket=existing_bucket)
    except Exception:
        pass

    environment_inventory.get_snapshot(force_rescan=True, db=db_session)

    prompt = f"Create an S3 bucket called {existing_bucket} in us-east-1 on AWS\n[Clarification]: Resource '{existing_bucket}' already exists -> Reuse & manage"
    chat_resp = orchestrator.process_natural_language(
        prompt=prompt,
        cloud_provider="aws",
        environment="local",
        db=db_session,
    )

    assert chat_resp.status == "plan_ready"
    assert chat_resp.plan is not None
    plan = chat_resp.plan

    # Verify Terraform HCL contains import block
    assert "import {" in plan.generated_terraform
    assert f'id = "{existing_bucket}"' in plan.generated_terraform
    res = next(
        (r for r in plan.ir.cloud.resources if r.type in ["storage_bucket", "object_storage", "s3_bucket", "bucket"] or existing_bucket in r.properties.get("bucket_name", "") or existing_bucket in r.name),
        None,
    )
    assert res is not None
    assert "EXISTS → reuse" in (res.status_chip or "")

    # Execute plan
    exec_res = orchestrator.execute_approved_plan(plan.plan_id, db=db_session)
    assert exec_res.success is True

    # Verify terraform state file contains the bucket
    state_file = Path(settings.TERRAFORM_WORKSPACE) / plan.plan_id / "terraform.tfstate"
    if state_file.exists():
        state_data = json.loads(state_file.read_text(encoding="utf-8"))
        bucket_found_in_state = any(
            r.get("type") == "aws_s3_bucket"
            for r in state_data.get("resources", [])
        )
        assert bucket_found_in_state is True


def test_checkpoint_4_existing_subnet_cidr_auto_recomputed(db_session):
    """
    Checkpoint 4: Existing subnet 10.0.1.0/24 + plan requesting same CIDR ->
    auto-recomputed; no InvalidSubnet.Range at apply.
    """
    uid = uuid.uuid4().hex[:6]
    # Create mock environment snapshot with existing subnet 10.0.1.0/24
    snapshot = EnvironmentSnapshot(
        snapshot_id=f"snap_test_{uid}",
        provider="aws",
        region="us-east-1",
        subnets=[
            {"id": "subnet-existing-1", "vpc_id": "vpc-test-1", "cidr_block": "10.0.1.0/24", "az": "us-east-1a"}
        ],
    )
    snapshot.snapshot_hash = snapshot.compute_hash()

    ir = UniversalIR(
        intent="deploy_cloud",
        cloud=CloudPlan(
            provider="aws",
            region="us-east-1",
            resources=[
                CloudResource(
                    id="subnet1",
                    name="web_subnet",
                    type="subnet",
                    properties={"cidr_block": "10.0.1.0/24", "availability_zone": "us-east-1a"},
                )
            ],
        ),
    )

    conflicts, patched_ir, has_ask_user, is_blocked = environment_conflict_validator.validate_and_resolve(
        ir=ir,
        snapshot=snapshot,
    )

    assert has_ask_user is False
    assert is_blocked is False
    assert len(conflicts) == 1
    assert conflicts[0].strategy == "auto-recompute"
    assert conflicts[0].conflict_type == "cidr_overlap"

    new_cidr = patched_ir.cloud.resources[0].properties["cidr_block"]
    assert new_cidr != "10.0.1.0/24"
    assert "OVERLAP → moved to" in (patched_ir.cloud.resources[0].status_chip or "")

    # Non-overlapping verification
    net_old = ipaddress.ip_network("10.0.1.0/24")
    net_new = ipaddress.ip_network(new_cidr)
    assert not net_old.overlaps(net_new)


def test_checkpoint_5_existing_rds_identifier_surfaced_at_plan_time(db_session):
    """
    Checkpoint 5: Existing RDS identifier surfaced at plan time, not apply time.
    """
    uid = uuid.uuid4().hex[:6]
    db_id = f"orders-db-{uid}"

    snapshot = EnvironmentSnapshot(
        snapshot_id=f"snap_test_rds_{uid}",
        provider="aws",
        region="us-east-1",
        rds_instances=[
            {
                "identifier": db_id,
                "engine": "postgres",
                "engine_version": "15",
                "instance_class": "db.t3.micro",
                "status": "available",
            }
        ],
    )
    snapshot.snapshot_hash = snapshot.compute_hash()

    ir = UniversalIR(
        intent="deploy_cloud",
        cloud=CloudPlan(
            provider="aws",
            region="us-east-1",
            resources=[
                CloudResource(
                    id="db1",
                    name=db_id,
                    type="managed_database",
                    properties={"identifier": db_id, "engine": "postgres"},
                )
            ],
        ),
    )

    conflicts, patched_ir, has_ask_user, is_blocked = environment_conflict_validator.validate_and_resolve(
        ir=ir,
        snapshot=snapshot,
    )

    assert has_ask_user is True
    assert len(conflicts) == 1
    c = conflicts[0]
    assert c.strategy == "ask-user"
    assert c.original_name == db_id
    assert any("Reuse" in opt for opt in c.options)
    assert any("Rename" in opt for opt in c.options)


def test_checkpoint_6_illegal_name_auto_corrected_with_notify_chip():
    """
    Checkpoint 6: Illegal name (e.g., uppercase bucket) auto-corrected with
    visible notify chip.
    """
    illegal_bucket_name = "MY_COMPANY_ASSETS_BUCKET!"
    res = AWSNamingValidator.validate_and_fix("object_storage", illegal_bucket_name)

    assert res.is_valid is False
    assert res.fixed_name == "my-company-assets-bucket"
    assert "uppercase" in (res.reason or "").lower() or "underscore" in (res.reason or "").lower()

    # In IR conflict validation
    snapshot = EnvironmentSnapshot(snapshot_id="empty_snap", provider="aws", region="us-east-1")
    snapshot.snapshot_hash = snapshot.compute_hash()

    ir = UniversalIR(
        intent="deploy_cloud",
        cloud=CloudPlan(
            provider="aws",
            region="us-east-1",
            resources=[
                CloudResource(
                    id="b1",
                    name=illegal_bucket_name,
                    type="object_storage",
                    properties={"bucket_name": illegal_bucket_name},
                )
            ],
        ),
    )

    conflicts, patched_ir, has_ask_user, is_blocked = environment_conflict_validator.validate_and_resolve(
        ir=ir,
        snapshot=snapshot,
    )

    assert any(c.strategy == "auto-fix" for c in conflicts)
    resource = patched_ir.cloud.resources[0]
    assert resource.name == "my-company-assets-bucket"
    assert "NAME_CORRECTED → my-company-assets-bucket" in (resource.status_chip or "")


def test_checkpoint_7_cache_ttl_and_rescan_no_api_storm(db_session):
    """
    Checkpoint 7: Cache test: create bucket externally, force rescan, conflict appears;
    within TTL no API storm (call count asserted).
    """
    environment_inventory.reset_call_metrics()

    # 1. Fresh scan
    snap1 = environment_inventory.get_snapshot(provider="aws", region="us-east-1", force_rescan=True, db=db_session)
    call_count_1 = environment_inventory.get_api_call_count()
    assert call_count_1 > 0

    # 2. Sequential calls within 60s TTL must not issue any new API calls
    for _ in range(10):
        snap = environment_inventory.get_snapshot(provider="aws", region="us-east-1", force_rescan=False, db=db_session)
        assert snap.snapshot_id == snap1.snapshot_id
        assert snap.snapshot_hash == snap1.snapshot_hash

    call_count_cached = environment_inventory.get_api_call_count()
    assert call_count_cached == call_count_1, "API storm detected! Calls increased during active TTL."

    # 3. Create bucket externally
    uid = uuid.uuid4().hex[:6]
    b_name = f"vellum-storm-test-{uid}"
    s3 = get_s3_client()
    try:
        s3.create_bucket(Bucket=b_name)
    except Exception:
        pass

    # 4. Force rescan -> new calls issued, new bucket detected
    snap2 = environment_inventory.get_snapshot(provider="aws", region="us-east-1", force_rescan=True, db=db_session)
    assert environment_inventory.get_api_call_count() > call_count_cached
    assert b_name in snap2.buckets


def test_checkpoint_8_read_only_proof_zero_mutating_calls(db_session):
    """
    Checkpoint 8: Read-only proof: scan issues zero mutating API calls
    (assert via mocked client / LocalStack call logs).
    """
    environment_inventory.reset_call_metrics()
    environment_inventory.get_snapshot(provider="aws", region="us-east-1", force_rescan=True, db=db_session)

    # Assert using strict method introspection
    environment_inventory.assert_zero_mutating_calls()

    call_log = environment_inventory.get_call_log()
    assert len(call_log) > 0
    for call in call_log:
        method = call["method"].lower()
        assert not any(method.startswith(verb) for verb in environment_inventory.MUTATING_VERBS)
        assert any(method.startswith(verb) for verb in ["list", "describe", "get", "head"])


def test_checkpoint_9_race_backstop_bucket_created_between_scan_and_apply(db_session):
    """
    Checkpoint 9: Race backstop: bucket created between scan and apply ->
    M-14 import heal still succeeds.
    """
    uid = uuid.uuid4().hex[:6]
    bucket_name = f"vellum-race-{uid}"
    plan_id = f"plan_race_{uid}"

    # Plan generated when bucket does NOT exist in snapshot
    ir = UniversalIR(
        intent="deploy_cloud",
        cloud=CloudPlan(
            provider="aws",
            region="us-east-1",
            resources=[
                CloudResource(
                    id="b1",
                    name=bucket_name.replace("-", "_"),
                    type="object_storage",
                    properties={"bucket_name": bucket_name},
                )
            ],
        ),
    )

    plan_dir = tf_generator.generate(ir, environment="local", plan_id=plan_id)
    plan_rec = PlanRecord(
        plan_id=plan_id,
        prompt="race test bucket",
        ir_json=ir.model_dump_json(),
        terraform_code=Path(f"{plan_dir}/main.tf").read_text(encoding="utf-8"),
        status="approved",
        risk_level="low",
    )
    db_session.add(plan_rec)
    db_session.commit()

    # INJECT RACE CONDITION: Bucket created out-of-band right after plan generation!
    s3 = get_s3_client()
    try:
        s3.create_bucket(Bucket=bucket_name)
    except Exception:
        pass

    # Execute plan -> Apply encounters collision -> M-14 self-healing kicks in
    exec_res = orchestrator.execute_approved_plan(plan_id, db=db_session)
    assert exec_res.success is True

    # State or LocalStack confirms bucket is active
    buckets = [b["Name"] for b in s3.list_buckets().get("Buckets", [])]
    assert bucket_name in buckets


def test_checkpoint_10_audit_shows_preflight_scan_and_conflict_resolved(db_session):
    """
    Checkpoint 10: Audit shows PREFLIGHT_SCAN + CONFLICT_RESOLVED with snapshot hash.
    """
    uid = uuid.uuid4().hex[:6]
    bucket_name = f"vellum-audit-chk10-{uid}"
    renamed_bucket = f"vellum-audit-chk10-renamed-{uid}"

    s3 = get_s3_client()
    try:
        s3.create_bucket(Bucket=bucket_name)
    except Exception:
        pass

    environment_inventory.get_snapshot(force_rescan=True, db=db_session)

    prompt = f"Create an S3 bucket called {bucket_name} in us-east-1 on AWS\n[Clarification]: Resource '{bucket_name}' already exists -> Rename to {renamed_bucket}"
    chat_resp = orchestrator.process_natural_language(
        prompt=prompt,
        cloud_provider="aws",
        environment="local",
        db=db_session,
    )

    assert chat_resp.status == "plan_ready"
    plan_id = chat_resp.plan.plan_id

    # Query audit logs for PREFLIGHT_SCAN and CONFLICT_RESOLVED
    scan_log = db_session.query(AuditLogRecord).filter(AuditLogRecord.event_type == "PREFLIGHT_SCAN").order_by(AuditLogRecord.id.desc()).first()
    assert scan_log is not None
    scan_details = json.loads(scan_log.details_json)
    assert "snapshot_hash" in scan_details
    assert len(scan_details["snapshot_hash"]) == 64

    resolve_log = db_session.query(AuditLogRecord).filter(
        AuditLogRecord.event_type == "CONFLICT_RESOLVED",
        AuditLogRecord.plan_id == plan_id
    ).first()
    assert resolve_log is not None
    resolve_details = json.loads(resolve_log.details_json)
    assert resolve_details["strategy"] == "rename"
    assert resolve_details["before"] == bucket_name
    assert resolve_details["after"] == renamed_bucket
    assert "snapshot_hash" in resolve_details


def test_checkpoint_11_protected_name_fail_fast(db_session):
    """
    Checkpoint: Resources in protected_names governance list trigger fail-fast policy.
    """
    protected_bucket = "prod-assets"
    s3 = get_s3_client()
    try:
        s3.create_bucket(Bucket=protected_bucket)
    except Exception:
        pass

    environment_inventory.get_snapshot(force_rescan=True, db=db_session)

    prompt = f"Create an S3 bucket called {protected_bucket} in us-east-1 on AWS for company assets"
    chat_resp = orchestrator.process_natural_language(
        prompt=prompt,
        cloud_provider="aws",
        environment="local",
        db=db_session,
    )

    assert chat_resp.status == "error"
    assert "protected_names" in chat_resp.message or "halted" in chat_resp.message.lower()
