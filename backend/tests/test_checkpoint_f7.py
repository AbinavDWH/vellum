import pytest
import json
from app.engines.orchestrator import orchestrator
from app.schemas.ir import UniversalIR
from app.main import format_plan_response
from app.models import PlanRecord
from app.database import SessionLocal


def test_f7_implementation_plan_emission():
    """Checkpoint F7: Planner emits implementation_plan with 5 ordered human-readable steps."""
    # Test for static site intent
    static_ir = UniversalIR(
        intent="deploy_static_site",
        cloud={
            "provider": "aws",
            "region": "us-east-1",
            "environment": "local",
            "resources": [
                {
                    "name": "vellum_website",
                    "type": "object_storage",
                    "properties": {"bucket_name": "my-site", "website": True},
                }
            ],
        },
        site_source={"type": "github", "repo_url": "https://github.com/octocat/Hello-World"},
    )
    plan_steps = orchestrator._build_implementation_plan(static_ir)
    assert len(plan_steps) == 5, f"Expected 5 implementation steps, got {len(plan_steps)}"
    
    phases = [s["phase"] for s in plan_steps]
    assert phases == ["infra", "config", "content", "verify", "handoff"], f"Unexpected phases: {phases}"

    # Verify each step has required fields
    for idx, step in enumerate(plan_steps):
        assert step["step_number"] == idx + 1
        assert "name" in step and step["name"]
        assert "description" in step and step["description"]
        assert step["status"] == "pending"

    # Static site specific step descriptions
    assert "S3" in plan_steps[0]["description"]
    assert "public-read" in plan_steps[1]["description"]
    assert "github" in plan_steps[2]["description"]
    assert "verification" in plan_steps[3]["description"].lower()
    assert "endpoint" in plan_steps[4]["description"].lower()


def test_f7_implementation_plan_in_vpc_plan():
    """Checkpoint F7: VPC plan emits implementation_plan with ordered steps."""
    vpc_ir = UniversalIR(
        intent="deploy_cloud",
        cloud={
            "provider": "aws",
            "region": "us-east-1",
            "environment": "local",
            "resources": [
                {
                    "name": "main_vpc",
                    "type": "virtual_network",
                    "properties": {"cidr_block": "10.0.0.0/16"},
                },
                {
                    "name": "public_subnet_1",
                    "type": "subnet",
                    "properties": {"cidr_block": "10.0.1.0/24", "public": True},
                },
            ],
        },
    )
    plan_steps = orchestrator._build_implementation_plan(vpc_ir)
    assert len(plan_steps) == 5
    phases = [s["phase"] for s in plan_steps]
    assert phases == ["infra", "config", "content", "verify", "handoff"]
    assert "VPC" in plan_steps[0]["description"]
    assert "Internet Gateway" in plan_steps[1]["description"]


def test_f7_format_plan_response_preserves_implementation_plan():
    """Checkpoint F7: format_plan_response populates implementation_plan."""
    db = SessionLocal()
    try:
        raw_ir = UniversalIR(
            intent="deploy_cloud",
            cloud={
                "provider": "aws",
                "region": "us-east-1",
                "environment": "local",
                "resources": [{"name": "test_vpc", "type": "virtual_network"}],
            },
        )
        plan_rec = PlanRecord(
            plan_id="plan_test_f7",
            prompt="create a vpc",
            intent="deploy_cloud",
            risk_level="low",
            status="awaiting_approval",
            ir_json=raw_ir.model_dump_json(),
            terraform_code="",
        )
        plan_resp = format_plan_response(plan_rec, db=db)
        assert plan_resp.implementation_plan is not None
        assert len(plan_resp.implementation_plan) == 5
        assert [s["phase"] for s in plan_resp.implementation_plan] == ["infra", "config", "content", "verify", "handoff"]
    finally:
        db.close()


def test_f7_execution_step_status_mapping():
    """Checkpoint F7: Test implementation step progression from pending -> active -> done or failed."""
    ir = UniversalIR(
        intent="deploy_cloud",
        cloud={
            "provider": "aws",
            "region": "us-east-1",
            "environment": "local",
            "resources": [{"name": "test_vpc", "type": "virtual_network"}],
        },
    )
    steps = orchestrator._build_implementation_plan(ir)
    assert len(steps) == 5

    # Simulate success progression
    for step in steps:
        assert step["status"] == "pending"

    # Verify when failure happens at verification step, verification phase is flagged
    failed_phase = "verify"
    updated_steps = []
    for step in steps:
        if step["phase"] == "infra" or step["phase"] == "config":
            step["status"] = "done"
        elif step["phase"] == failed_phase:
            step["status"] = "failed"
            step["agent_decision"] = "Functional route check failed: 0.0.0.0/0 route missing"
        else:
            step["status"] = "pending"
        updated_steps.append(step)

    assert updated_steps[0]["status"] == "done"
    assert updated_steps[1]["status"] == "done"
    assert updated_steps[3]["status"] == "failed"
    assert "Functional route check failed" in updated_steps[3]["agent_decision"]
    assert updated_steps[4]["status"] == "pending"

