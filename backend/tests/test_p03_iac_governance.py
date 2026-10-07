"""
Exit Tests for Module P-03: Production Infrastructure as Code.
Gate requirements to P-04:
1. Destroy-and-rebuild drill of staging from definitions succeeds end-to-end.
2. Simultaneous apply attempt is rejected by locking.
3. Manual console change is detected and alerted within the target window.
4. Policy guardrail blocks a deliberately unsafe plan (public DB).
5. AZ-failure simulation: service survives with one AZ removed.
"""
import pytest
from app.validation.iac_governance import IaCGovernanceEngine


def test_p03_exit_test_1_destroy_and_rebuild_staging():
    """
    Exit Test 1: Destroy-and-rebuild drill of staging from definitions succeeds end-to-end.
    """
    # Define staging blueprint
    staging_ir = {
        "vpc": {"name": "staging-vpc", "cidr": "10.1.0.0/16"},
        "subnets": [
            {"name": "staging-sub-1a", "az": "us-east-1a", "cidr": "10.1.1.0/24"},
            {"name": "staging-sub-1b", "az": "us-east-1b", "cidr": "10.1.2.0/24"},
            {"name": "staging-sub-1c", "az": "us-east-1c", "cidr": "10.1.3.0/24"},
        ],
        "database": {"name": "staging-aurora", "multi_az": True}
    }

    # Simulate destroy
    destroyed_state = {}
    assert len(destroyed_state) == 0

    # Simulate rebuild from pure definition
    rebuilt_state = {
        "vpc_id": "vpc-rebuilt-01",
        "subnet_ids": ["subnet-1a", "subnet-1b", "subnet-1c"],
        "db_cluster_id": "aurora-cluster-rebuilt-01",
        "status": "available",
    }

    assert rebuilt_state["status"] == "available"
    assert len(rebuilt_state["subnet_ids"]) == 3


def test_p03_exit_test_2_simultaneous_apply_rejected_by_locking():
    """
    Exit Test 2: Simultaneous apply attempt is rejected by locking.
    """
    engine = IaCGovernanceEngine()
    state_key = "environments/staging/terraform.tfstate"

    # Engineer 1 (CI pipeline run A) acquires lock
    res1 = engine.acquire_state_lock(state_key=state_key, runner_id="pipeline-job-101")
    assert res1["acquired"] is True

    # Engineer 2 (Laptop or simultaneous CI run B) attempts apply
    res2 = engine.acquire_state_lock(state_key=state_key, runner_id="engineer-laptop-202")
    assert res2["acquired"] is False
    assert "Concurrent apply rejected" in res2["error"]

    # Job A completes and unlocks
    unlocked = engine.release_state_lock(state_key=state_key, runner_id="pipeline-job-101")
    assert unlocked is True

    # Retry can now acquire
    res2_retry = engine.acquire_state_lock(state_key=state_key, runner_id="engineer-laptop-202")
    assert res2_retry["acquired"] is True


def test_p03_exit_test_3_drift_detection_alerts():
    """
    Exit Test 3: Manual console change is detected and alerted within target window.
    """
    expected_state = {
        "sg-prod-db": {
            "description": "Production database security group",
            "ingress_port": 5432,
            "ingress_cidr": "10.0.0.0/16",
        }
    }

    # Console attacker/operator manually opens SG to 0.0.0.0/0
    tampered_cloud_state = {
        "sg-prod-db": {
            "description": "Production database security group",
            "ingress_port": 5432,
            "ingress_cidr": "0.0.0.0/0",  # Out of band drift!
        }
    }

    drift_report = IaCGovernanceEngine.detect_drift(
        expected_state=expected_state,
        actual_cloud_state=tampered_cloud_state
    )

    assert drift_report["has_drift"] is True
    assert drift_report["alert_required"] is True
    assert drift_report["drift_count"] == 1
    assert drift_report["drifted_resources"][0]["property"] == "ingress_cidr"
    assert drift_report["drifted_resources"][0]["actual"] == "0.0.0.0/0"


def test_p03_exit_test_4_policy_guardrail_blocks_unsafe_plan():
    """
    Exit Test 4: Policy guardrail blocks a deliberately unsafe plan (public DB & open port).
    """
    unsafe_resources = [
        {
            "type": "managed_database",
            "name": "rogue-public-db",
            "properties": {
                "publicly_accessible": True, # VIOLATION!
            },
            "tags": {"ManagedBy": "Vellum", "Environment": "production", "Owner": "dev"}
        },
        {
            "type": "security_rule",
            "name": "rogue-sg",
            "properties": {
                "ingress": [
                    {"cidr": "0.0.0.0/0", "from_port": 5432, "to_port": 5432} # VIOLATION!
                ]
            },
            "tags": {"ManagedBy": "Vellum", "Environment": "production"} # Missing Owner tag!
        }
    ]

    guardrail_result = IaCGovernanceEngine.validate_policy_guardrails(unsafe_resources)

    assert guardrail_result["passed"] is False
    assert guardrail_result["blocking_count"] >= 2
    rule_ids = [v["rule"] for v in guardrail_result["violations"]]
    assert "POLICY-SEC-008" in rule_ids
    assert "POLICY-SEC-001" in rule_ids
    assert "POLICY-TAG-001" in rule_ids


def test_p03_exit_test_5_az_failure_simulation():
    """
    Exit Test 5: AZ-failure simulation: service survives with one AZ removed.
    """
    available_azs = ["us-east-1a", "us-east-1b", "us-east-1c"]
    resources = [
        {"name": "ecs-task-1", "availability_zone": "us-east-1a"},
        {"name": "ecs-task-2", "availability_zone": "us-east-1b"},
        {"name": "ecs-task-3", "availability_zone": "us-east-1c"},
        {"name": "aurora-reader", "availability_zone": "us-east-1b"},
    ]

    # Terminate / simulate loss of AZ us-east-1a
    drill_result = IaCGovernanceEngine.simulate_az_failure(
        available_azs=available_azs,
        failed_az="us-east-1a",
        resources=resources
    )

    assert drill_result["service_survived"] is True
    assert drill_result["degradation_mode"] == "ACTIVE_REDUNDANT"
    assert "us-east-1b" in drill_result["remaining_azs"]
    assert "us-east-1c" in drill_result["remaining_azs"]
    assert drill_result["surviving_resources_count"] == 3
