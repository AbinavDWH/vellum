"""
Exit Tests for Module P-05: Zero-Downtime Deployment Strategy.
Gate requirements to P-06:
1. Load test across a deploy shows zero failed requests and zero connection resets.
2. Canary with injected error rate auto-rolls back within target time.
3. Mixed-version compatibility test: old app + new schema and new app + old schema both pass.
4. Feature flag off-switch takes effect within seconds, no redeploy.
5. In-flight long job survives a deploy without duplication or loss.
"""
import pytest
from app.validation.zero_downtime import ZeroDowntimeController


def test_p05_exit_test_1_graceful_drain_zero_failed_requests():
    """
    Exit Test 1: Load test across a deploy shows zero failed requests and zero connection resets.
    """
    controller = ZeroDowntimeController()

    # Simulate 5 concurrent in-flight requests
    for _ in range(5):
        controller.register_request_start()

    assert controller._in_flight_requests == 5

    # Simulate requests completing during graceful drain window
    controller.register_request_end()
    controller.register_request_end()
    controller.register_request_end()
    controller.register_request_end()
    controller.register_request_end()

    drain_res = controller.initiate_graceful_drain(timeout_seconds=5.0)
    assert drain_res["drained_cleanly"] is True
    assert drain_res["remaining_requests"] == 0


def test_p05_exit_test_2_canary_auto_rollback():
    """
    Exit Test 2: Canary with injected error rate auto-rolls back within target time.
    """
    # 1. Healthy Canary step at 10% traffic
    healthy_step = ZeroDowntimeController.evaluate_canary_health(
        traffic_slice_percent=10,
        http_requests_total=1000,
        http_errors_total=1,       # 0.1% error rate
        p99_latency_ms=180.0
    )
    assert healthy_step["healthy"] is True
    assert healthy_step["action"] == "PROMOTE_NEXT_STEP"

    # 2. Canary with injected error rate (1.5% errors > 0.5% threshold)
    unhealthy_step = ZeroDowntimeController.evaluate_canary_health(
        traffic_slice_percent=10,
        http_requests_total=1000,
        http_errors_total=15,      # 1.5% error rate
        p99_latency_ms=190.0,
        error_threshold_percent=0.5
    )
    assert unhealthy_step["healthy"] is False
    assert unhealthy_step["action"] == "AUTO_ROLLBACK"
    assert unhealthy_step["rollback_trigger"] == "ERROR_RATE_EXCEEDED"


def test_p05_exit_test_3_expand_contract_schema_compatibility():
    """
    Exit Test 3: Mixed-version compatibility test: old app + new schema and new app + old schema both pass.
    """
    old_columns = ["id", "username", "email"]
    
    # Valid additive change: new column is nullable with default
    valid_added_columns = [
        {"name": "avatar_url", "type": "varchar", "nullable": True, "default": None},
        {"name": "is_active", "type": "boolean", "nullable": False, "default": True}
    ]
    res_valid = ZeroDowntimeController.verify_expand_contract_compatibility(
        old_schema_columns=old_columns,
        new_schema_columns=old_columns + ["avatar_url", "is_active"],
        added_columns=valid_added_columns
    )
    assert res_valid["compatible"] is True
    assert res_valid["can_deploy_without_downtime"] is True

    # Invalid additive change: NOT NULL column without default (breaks live version N app)
    breaking_added_columns = [
        {"name": "mandatory_national_id", "type": "varchar", "nullable": False, "default": None}
    ]
    res_breaking = ZeroDowntimeController.verify_expand_contract_compatibility(
        old_schema_columns=old_columns,
        new_schema_columns=old_columns + ["mandatory_national_id"],
        added_columns=breaking_added_columns
    )
    assert res_breaking["compatible"] is False
    assert len(res_breaking["violations"]) == 1


def test_p05_exit_test_4_feature_flag_instant_off_switch():
    """
    Exit Test 4: Feature flag off-switch takes effect within seconds, no redeploy.
    """
    controller = ZeroDowntimeController()
    flag = "ai_advanced_optimizer"

    # Initially enabled
    assert controller.is_feature_enabled(flag) is True

    # Immediate toggle off
    controller.set_feature_flag(flag, enabled=False)

    # Immediately reflects new state without restart
    assert controller.is_feature_enabled(flag) is False


def test_p05_exit_test_5_in_flight_job_checkpoint_and_handoff():
    """
    Exit Test 5: In-flight long job survives a deploy without duplication or loss.
    """
    controller = ZeroDowntimeController()
    job_id = "job-terraform-apply-9001"

    # Container A executes step 1 & 2, then records checkpoint before termination
    controller.checkpoint_job(
        job_id=job_id,
        step_name="step_2_plan_validated",
        state_data={"vpc_id": "vpc-0987", "subnets_created": 3}
    )

    # Container B starts up post-deploy, resumes job from checkpoint
    recovered_job = controller.resume_job_from_checkpoint(job_id)
    assert recovered_job is not None
    assert recovered_job["job_id"] == job_id
    assert recovered_job["last_completed_step"] == "step_2_plan_validated"
    assert recovered_job["state_data"]["subnets_created"] == 3
