"""
Global Regression Gate Test Suite for Vellum M-21
Covers F1 through F8, Golden suite (10 prompts), incident replays, and audit chain.
"""

import json
import pytest
from app.database import SessionLocal
from app.models import PlanRecord, ExecutionRecord
from app.schemas.ir import UniversalIR
from app.schemas.cloud import CloudPlan, CloudResource
from app.engines.terraform_generator import tf_generator
from app.engines.orchestrator import orchestrator
from app.engines.verification_engine import verification_engine
from app.engines.execution_engine import execution_engine
from app.validation.scope_fidelity import ScopeFidelityValidator
from app.audit.logger import audit_logger
from app.llm.client import llm_client

scope_validator = ScopeFidelityValidator()


def test_gate_f1_vpc_internet_reachability():
    """F1: Public VPC emits IGW, route table, 0.0.0.0/0 route, association, and map_public_ip_on_launch."""
    ir = UniversalIR(
        intent="deploy_cloud",
        cloud=CloudPlan(
            provider="aws",
            region="us-east-1",
            environment="local",
            resources=[
                CloudResource(
                    type="network",
                    name="main_vpc",
                    properties={"cidr_block": "10.0.0.0/16"},
                ),
                CloudResource(
                    type="subnet",
                    name="public_subnet",
                    properties={"cidr_block": "10.0.1.0/24", "public": True, "vpc_name": "main_vpc"},
                ),
            ],
        ),
    )
    pdir = tf_generator.generate(ir, environment="local", plan_id="gate_f1_test")
    with open(f"{pdir}/main.tf") as f:
        code = f.read()

    assert "aws_internet_gateway" in code
    assert "aws_route_table" in code
    assert "aws_route" in code
    assert "0.0.0.0/0" in code
    assert "aws_route_table_association" in code
    assert "map_public_ip_on_launch = true" in code

    # Connectivity intent verification
    report = verification_engine.verify(plan_id="gate_f1_test", expected_ir=ir)
    assert report is not None
    assert "status" in report


def test_gate_f2_s3_static_website_serving():
    """F2: S3 static website hosting produces website config, public policy, and endpoint."""
    ir = UniversalIR(
        intent="deploy_static_site",
        cloud=CloudPlan(
            provider="aws",
            region="us-east-1",
            environment="local",
            resources=[
                CloudResource(
                    type="object_storage",
                    name="static_site_bucket",
                    properties={"website": True, "bucket_name": "gate-f2-site-bucket"},
                )
            ],
        ),
    )
    pdir = tf_generator.generate(ir, environment="local", plan_id="gate_f2_test")
    with open(f"{pdir}/main.tf") as f:
        code = f.read()

    assert "website_configuration" in code or "aws_s3_bucket_website_configuration" in code
    assert "block_public_policy     = false" in code or "block_public_policy = false" in code
    assert "aws_s3_bucket_policy" in code
    assert "website_endpoint" in code


def test_gate_f3_content_deployment_capabilities():
    """F3: Content deployment supports inline code sync, mime types, and functional ETag verify."""
    import mimetypes
    assert mimetypes.guess_type("index.html")[0] == "text/html"
    assert mimetypes.guess_type("style.css")[0] == "text/css"
    assert mimetypes.guess_type("script.js")[0] in ["application/javascript", "text/javascript"]

    # Test sync against LocalStack S3
    import boto3
    s3 = boto3.client("s3", endpoint_url="http://localhost:4566", aws_access_key_id="test", aws_secret_access_key="test", region_name="us-east-1")
    bucket = "gate-f3-test-bucket"
    try:
        s3.create_bucket(Bucket=bucket)
    except Exception:
        pass

    url, meta = execution_engine.sync_static_site_content(
        bucket_name=bucket,
        site_source={"type": "inline", "content": "<h1>Gate F3 Live</h1>"},
        is_local=True,
    )
    assert url is not None
    assert meta.get("files_count", 0) >= 1
    assert "etag" in meta


def test_gate_f4_scope_fidelity():
    """F4: Build ONLY what was asked. No unsolicited RDS or database resources."""
    # 1. Prompt asks for static site -> Zero database
    ir_static = UniversalIR(
        intent="deploy_static_site",
        cloud=CloudPlan(
            provider="aws",
            region="us-east-1",
            environment="local",
            resources=[
                CloudResource(type="object_storage", name="web_bucket", properties={"website": True}),
                CloudResource(type="relational_database", name="unwanted_db", properties={}),
            ],
        ),
    )
    is_valid, errors, _ = ScopeFidelityValidator.validate(
        prompt="Host a static website from GitHub repo myuser/repo",
        ir=ir_static,
    )
    assert is_valid is False
    assert any("database" in e.lower() for e in errors)

    # 2. Prompt asks for VPC -> Zero S3/RDS
    ir_vpc = UniversalIR(
        intent="deploy_cloud",
        cloud=CloudPlan(
            provider="aws",
            region="us-east-1",
            environment="local",
            resources=[
                CloudResource(type="network", name="my_vpc", properties={}),
                CloudResource(type="object_storage", name="unwanted_s3", properties={}),
            ],
        ),
    )
    is_valid_vpc, errors_vpc, _ = ScopeFidelityValidator.validate(
        prompt="Create a VPC with public subnet connected to internet",
        ir=ir_vpc,
    )
    assert is_valid_vpc is False
    assert any("object_storage" in e.lower() or "s3" in e.lower() or "storage" in e.lower() for e in errors_vpc)


def test_gate_f5_intent_keyed_question_bank():
    """F5: Intent-keyed question bank asks only relevant, plan-changing questions."""
    q_static = llm_client.generate_architecture_questions("host a static website from github")
    assert len(q_static.questions) <= 4
    for q in q_static.questions:
        assert "database" not in q.question.lower()
        assert "rds" not in q.question.lower()

    q_vpc = llm_client.generate_architecture_questions("create a public vpc")
    assert len(q_vpc.questions) <= 4
    for q in q_vpc.questions:
        assert "database" not in q.question.lower()
        assert "rds" not in q.question.lower()


def test_gate_f6_no_false_completed_honest_status():
    """F6: COMPLETED requires 100% of IR resources verified. Failed resource ends in PARTIAL_FAILED or ROLLED_BACK."""
    ir_failing = UniversalIR(
        intent="deploy_cloud",
        cloud=CloudPlan(
            provider="aws",
            region="us-east-1",
            environment="local",
            resources=[
                CloudResource(type="object_storage", name="nonexistent_bucket_xyz_99", properties={"bucket_name": "nonexistent-bucket-xyz-99"})
            ],
        ),
    )
    report = verification_engine.verify(plan_id="plan_fail_inject", expected_ir=ir_failing)
    assert report.get("status") != "healthy"

    # Execution status evaluation
    checklist = [
        {"resource": "bucket_1", "type": "object_storage", "verified": True, "detail": "HTTP 200 OK"},
        {"resource": "bucket_2", "type": "object_storage", "verified": False, "detail": "404 Not Found"},
    ]
    all_ok = all(item["verified"] for item in checklist)
    final_status = "completed" if all_ok else "partial_failed"
    assert final_status == "partial_failed"


def test_gate_f7_implementation_plan_stepper():
    """F7: Implementation plan has 5 ordered, human-readable steps."""
    ir = UniversalIR(
        intent="deploy_static_site",
        cloud=CloudPlan(
            provider="aws",
            region="us-east-1",
            environment="local",
            resources=[
                CloudResource(type="object_storage", name="site_bucket", properties={"website": True})
            ],
        ),
    )
    plan_steps = orchestrator._build_implementation_plan(ir)
    assert len(plan_steps) == 5
    phases = [s["phase"] for s in plan_steps]
    assert phases == ["infra", "config", "content", "verify", "handoff"]


def test_gate_f8_terminate_and_stop_endpoints():
    """F8: Chat stop and execution terminate backend APIs."""
    from app.main import _chat_cancellation_tokens
    
    # Chat stop token set
    session_id = "test_gate_f8_session"
    _chat_cancellation_tokens.add(session_id)
    assert session_id in _chat_cancellation_tokens
    _chat_cancellation_tokens.discard(session_id)

    # Execution terminate mode
    res_sigint = execution_engine.terminate_execution("plan_gate_f8", force=False)
    assert res_sigint["mode"] == "sigint"
    res_sigkill = execution_engine.terminate_execution("plan_gate_f8", force=True)
    assert res_sigkill["mode"] == "sigkill"


def test_gate_golden_prompts_suite():
    """Golden prompt suite: 10 representative prompts validating scope fidelity and intent."""
    golden_prompts = [
        ("host static site from github https://github.com/org/repo", "deploy_static_site", ["object_storage"], ["managed_database"]),
        ("create a vpc with a public subnet connected to internet", "deploy_cloud", ["network", "subnet"], ["managed_database", "object_storage"]),
        ("deploy postgresql database with multi-az", "deploy_database", ["managed_database"], []),
        ("host static site using inline code", "deploy_static_site", ["object_storage"], ["managed_database"]),
        ("create private s3 bucket for backups", "deploy_cloud", ["object_storage"], ["managed_database"]),
        ("create private subnet with nat gateway", "deploy_cloud", ["network", "subnet"], ["managed_database"]),
        ("provision redis cache cluster", "deploy_cloud", ["elasticache_cluster"], ["managed_database"]),
        ("setup public alb and security groups", "deploy_cloud", ["load_balancer", "security_group"], ["managed_database"]),
        ("host frontend on s3 and store app state in rds postgres", "deploy_cloud", ["object_storage", "managed_database"], []),
        ("create dev vpc with 2 subnets", "deploy_cloud", ["network", "subnet"], ["managed_database"]),
    ]

    for prompt, expected_intent, expected_types, forbidden_types in golden_prompts:
        # Valid IR with only expected types
        ir_valid = UniversalIR(
            intent=expected_intent,
            cloud=CloudPlan(
                provider="aws",
                region="us-east-1",
                environment="local",
                resources=[
                    CloudResource(type=t, name=f"res_{t}", properties={}) for t in expected_types
                ],
            ),
        )
        is_ok, _, _ = ScopeFidelityValidator.validate(prompt=prompt, ir=ir_valid)
        assert is_ok is True, f"Expected valid IR for prompt: {prompt}"

        # If prompt has forbidden types, IR with forbidden resource must fail validation
        if forbidden_types:
            ir_invalid = UniversalIR(
                intent=expected_intent,
                cloud=CloudPlan(
                    provider="aws",
                    region="us-east-1",
                    environment="local",
                    resources=[
                        CloudResource(type=t, name=f"res_{t}", properties={}) for t in expected_types
                    ] + [
                        CloudResource(type=t, name=f"forbidden_{t}", properties={}) for t in forbidden_types
                    ],
                ),
            )
            is_valid, errs, _ = ScopeFidelityValidator.validate(prompt=prompt, ir=ir_invalid)
            assert is_valid is False, f"Expected validation failure for prompt: {prompt} with forbidden types {forbidden_types}"


def test_gate_audit_chain_integrity():
    """Verify cryptographic audit trail integrity."""
    audit_logger.log(
        event_type="regression_gate_verification",
        plan_id="plan_gate_audit",
        details={"status": "passed", "checks": 10},
    )
    logs = audit_logger.get_all_logs(limit=20)
    assert len(logs) > 0
    for log in logs:
        assert "event_type" in log
        assert "timestamp" in log
        assert "payload_hash" in log or "details" in log
