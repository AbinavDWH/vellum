"""
Exit Tests for Module P-06: Observability, Alerting & On-Call.
Gate requirements to P-07:
1. Injected latency/error incident is paged within target detection time.
2. One request traceable UI → backend → executor → verification with a single ID.
3. Queue-stall simulation raises a backlog alert before user impact.
4. Alert-to-runbook mapping audit: zero orphan alerts.
5. Log retention drill: 90-day-old audit entry retrievable and hash-verified.
"""
import pytest
from app.validation.observability import ObservabilityEngine


def test_p06_exit_test_1_golden_signals_incident_paging_sla():
    """
    Exit Test 1: Injected latency/error incident is paged within target detection time (< 180s).
    """
    # Simulate an injected 5xx error spike (3.5% error rate, threshold is 0.5%) detected in 42 seconds
    incident = ObservabilityEngine.evaluate_slo_incident(
        metric_name="http_5xx_rate",
        value=3.5,
        threshold=0.5,
        incident_detection_seconds=42.0
    )

    assert incident["breached"] is True
    assert incident["within_detection_sla"] is True
    assert incident["paged"] is True
    assert incident["detection_seconds"] < ObservabilityEngine.MAX_DETECTION_SLA_SECONDS


def test_p06_exit_test_2_end_to_end_distributed_trace():
    """
    Exit Test 2: One request traceable UI → backend → executor → verification with a single ID.
    """
    engine = ObservabilityEngine()
    correlation_id = "req-trace-7744aa88"

    # Step 1: UI sends plan request
    engine.record_trace_span(correlation_id, service="frontend_ui", operation="submit_nl_prompt")
    # Step 2: Backend receives and parses
    engine.record_trace_span(correlation_id, service="backend_api", operation="parse_ir")
    # Step 3: LLM generates plan
    engine.record_trace_span(correlation_id, service="llm_inference", operation="generate_schema")
    # Step 4: Execution Engine provisions
    engine.record_trace_span(correlation_id, service="execution_engine", operation="terraform_apply")
    # Step 5: Verification Engine audits
    engine.record_trace_span(correlation_id, service="verification_engine", operation="drift_audit")

    # Fetch trace
    trace = engine.get_full_trace(correlation_id)
    assert len(trace) == 5
    services = [span["service"] for span in trace]
    assert "frontend_ui" in services
    assert "backend_api" in services
    assert "llm_inference" in services
    assert "execution_engine" in services
    assert "verification_engine" in services
    assert all(span["correlation_id"] == correlation_id for span in trace)


def test_p06_exit_test_3_queue_stall_alert():
    """
    Exit Test 3: Queue-stall simulation raises a backlog alert before user impact.
    """
    # Normal queue
    normal_q = ObservabilityEngine.check_queue_backlog(queue_depth=5, oldest_message_age_seconds=12.0)
    assert normal_q["is_stalled"] is False
    assert normal_q["alert_triggered"] is False

    # Stalled queue: messages waiting 75s (> 60s threshold)
    stalled_q = ObservabilityEngine.check_queue_backlog(queue_depth=120, oldest_message_age_seconds=75.0)
    assert stalled_q["is_stalled"] is True
    assert stalled_q["alert_triggered"] is True
    assert stalled_q["action_required"] == "SCALE_WORKERS"


def test_p06_exit_test_4_zero_orphan_alerts_audit():
    """
    Exit Test 4: Alert-to-runbook mapping audit: zero orphan alerts.
    """
    engine = ObservabilityEngine()
    audit_report = engine.audit_alert_runbooks()

    assert audit_report["compliant"] is True
    assert audit_report["orphan_count"] == 0
    assert len(audit_report["orphan_alerts"]) == 0
    assert audit_report["total_alerts"] >= 4


def test_p06_exit_test_5_log_retention_and_hash_verification():
    """
    Exit Test 5: Log retention drill: 90-day-old audit entry retrievable and hash-verified.
    """
    engine = ObservabilityEngine()
    simulated_date = "2026-07-07"  # 90 days prior
    payload = {
        "event": "APPROVAL_GRANTED",
        "plan_id": "plan-archived-90d-01",
        "operator": "lead-architect",
        "hash": "c8b41f..."
    }

    # Archive entry
    entry_id = "audit-log-20260707-001"
    recorded_hash = engine.archive_audit_entry(entry_id, payload, simulated_date)
    assert recorded_hash is not None

    # Retrieve and verify after 90 days
    retrieval_res = engine.retrieve_and_verify_archive(entry_id)
    assert retrieval_res["verified"] is True
    assert retrieval_res["recorded_hash"] == recorded_hash
    assert retrieval_res["recalculated_hash"] == recorded_hash
    assert retrieval_res["date"] == simulated_date
