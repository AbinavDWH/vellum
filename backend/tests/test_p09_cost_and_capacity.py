"""
Exit Tests for Module P-09: Cost, Capacity & Lifecycle Governance.
Gate requirements to P-10:
1. Injected spend anomaly alerts within target time with owner attribution.
2. Load test at 3× baseline: autoscaling holds SLOs, then scales back down.
3. Lifecycle policy drill: expired data tiered/deleted on schedule, retrievable classes intact.
4. Non-prod environments auto-downscale off-hours and recover on schedule.
"""
import datetime
import pytest
from app.validation.cost_governance import CostGovernanceEngine


def test_p09_exit_test_1_spend_anomaly_detection_with_attribution():
    """
    Exit Test 1: Injected spend anomaly alerts within target time with owner attribution.
    """
    # Injected runaway workload ($2,850 spend against $2,500 budget)
    tags = {
        "Owner": "ml-platform-team",
        "Environment": "staging",
        "Project": "Vellum"
    }
    anomaly = CostGovernanceEngine.evaluate_spend_anomaly(
        current_spend_usd=2850.0,
        budget_usd=2500.0,
        resource_tags=tags
    )

    assert anomaly["anomaly_detected"] is True
    assert anomaly["alert_level"] == "CRITICAL"
    assert anomaly["owner"] == "ml-platform-team"
    assert anomaly["utilization_pct"] == 114.0


def test_p09_exit_test_2_autoscaling_under_3x_baseline():
    """
    Exit Test 2: Load test at 3× baseline: autoscaling holds SLOs, then scales back down.
    """
    autoscale_result = CostGovernanceEngine.simulate_3x_traffic_autoscaling(
        baseline_rps=100,
        peak_rps=300,
        initial_instances=2
    )

    assert autoscale_result["slo_maintained"] is True
    assert autoscale_result["scaled_instances"] == 6
    assert autoscale_result["scale_up_seconds"] <= 60.0
    assert autoscale_result["p95_latency_ms"] <= 400.0
    assert autoscale_result["scaled_down_cleanly"] is True
    assert autoscale_result["final_instances"] == 2


def test_p09_exit_test_3_storage_lifecycle_expiration_and_tiering():
    """
    Exit Test 3: Lifecycle policy drill: expired data tiered/deleted on schedule, retrievable classes intact.
    """
    # 1. 15-day-old scratch workspace object -> PURGE
    scratch_rule = CostGovernanceEngine.evaluate_storage_lifecycle(
        object_name="scratch/temp_plan_01.json",
        age_days=15,
        data_class="scratch"
    )
    assert scratch_rule["action"] == "PURGE_DELETED"

    # 2. 95-day-old execution artifact -> TIER TO GLACIER
    artifact_rule = CostGovernanceEngine.evaluate_storage_lifecycle(
        object_name="artifacts/plan_e44a.tar.gz",
        age_days=95,
        data_class="execution_artifact"
    )
    assert artifact_rule["action"] == "TIER_TO_GLACIER"

    # 3. 120-day-old audit log -> RETAIN IMMUTABLE
    audit_rule = CostGovernanceEngine.evaluate_storage_lifecycle(
        object_name="audit/2026-06-01-trail.log",
        age_days=120,
        data_class="audit_log"
    )
    assert audit_rule["action"] == "RETAIN_IMMUTABLE_WORM"


def test_p09_exit_test_4_non_prod_off_hours_downscale():
    """
    Exit Test 4: Non-prod environments auto-downscale off-hours and recover on schedule.
    """
    # Nighttime in staging (22:30 UTC Tuesday) -> DOWNSCALED
    tuesday_night = datetime.datetime(2026, 10, 6, 22, 30, tzinfo=datetime.timezone.utc)
    res_night = CostGovernanceEngine.evaluate_non_prod_scheduler(tuesday_night, environment="staging")
    assert res_night["downscaled"] is True
    assert res_night["target_state"] == "STOPPED_OR_MINIMAL"
    assert res_night["cost_saving_active"] is True

    # Working hours in staging (11:00 UTC Wednesday) -> RUNNING FULL
    wednesday_work = datetime.datetime(2026, 10, 7, 11, 0, tzinfo=datetime.timezone.utc)
    res_day = CostGovernanceEngine.evaluate_non_prod_scheduler(wednesday_work, environment="staging")
    assert res_day["downscaled"] is False
    assert res_day["target_state"] == "RUNNING_FULL"

    # Production never auto-downscales
    prod_night = CostGovernanceEngine.evaluate_non_prod_scheduler(tuesday_night, environment="production")
    assert prod_night["downscaled"] is False
    assert prod_night["target_state"] == "RUNNING_FULL"
