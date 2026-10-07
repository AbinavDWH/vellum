"""
Zero-downtime deployment, canary analysis, expand-contract migrations, feature flags, and job handoff.
Implements controls for Module P-05 (Zero-Downtime Deployment Strategy).
"""
import time
import datetime
from typing import Dict, Any, List, Optional
import structlog

logger = structlog.get_logger(__name__)


class ZeroDowntimeController:
    """
    Controls zero-downtime deployment invariants:
    1. Connection draining & graceful shutdown
    2. Metric-gated canary evaluation & auto-rollback
    3. Expand-contract schema compatibility verification
    4. Instant feature flag off-switch
    5. In-flight job checkpointing & graceful worker handoff
    """

    def __init__(self):
        self._in_flight_requests = 0
        self._is_draining = False
        self._feature_flags: Dict[str, bool] = {
            "ai_advanced_optimizer": True,
            "canary_mode": False,
            "streaming_v2": True,
        }
        self._execution_checkpoints: Dict[str, Dict[str, Any]] = {}

    # 1. Connection Draining
    def register_request_start(self):
        if self._is_draining:
            raise RuntimeError("Server is draining connections. Do not route new requests.")
        self._in_flight_requests += 1

    def register_request_end(self):
        if self._in_flight_requests > 0:
            self._in_flight_requests -= 1

    def initiate_graceful_drain(self, timeout_seconds: float = 25.0) -> Dict[str, Any]:
        """
        Marks readiness probe as unready and drains in-flight requests.
        """
        self._is_draining = True
        start = time.time()
        # Drain active requests
        while self._in_flight_requests > 0 and (time.time() - start) < timeout_seconds:
            time.sleep(0.01)

        drained_cleanly = self._in_flight_requests == 0
        return {
            "drained_cleanly": drained_cleanly,
            "remaining_requests": self._in_flight_requests,
            "drain_time_seconds": round(time.time() - start, 3),
        }

    # 2. Canary Analyzer
    @classmethod
    def evaluate_canary_health(
        cls,
        traffic_slice_percent: int,
        http_requests_total: int,
        http_errors_total: int,
        p99_latency_ms: float,
        error_threshold_percent: float = 0.5,
        max_p99_latency_ms: float = 500.0
    ) -> Dict[str, Any]:
        """
        Monitors canary metrics. If error rate > threshold, triggers automated rollback.
        """
        error_rate = (http_errors_total / http_requests_total * 100) if http_requests_total > 0 else 0.0

        error_violation = error_rate > error_threshold_percent
        latency_violation = p99_latency_ms > max_p99_latency_ms

        should_rollback = error_violation or latency_violation

        return {
            "traffic_slice_percent": traffic_slice_percent,
            "error_rate_percent": round(error_rate, 2),
            "p99_latency_ms": p99_latency_ms,
            "healthy": not should_rollback,
            "action": "AUTO_ROLLBACK" if should_rollback else "PROMOTE_NEXT_STEP",
            "rollback_trigger": "ERROR_RATE_EXCEEDED" if error_violation else ("LATENCY_EXCEEDED" if latency_violation else None),
        }

    # 3. Expand-Contract Schema Compatibility
    @classmethod
    def verify_expand_contract_compatibility(
        cls,
        old_schema_columns: List[str],
        new_schema_columns: List[str],
        added_columns: List[Dict[str, Any]]
    ) -> Dict[str, Any]:
        """
        Enforces that new columns added during Expand phase are nullable or have defaults,
        so running version N of the application does not fail queries.
        """
        violations = []
        for col in added_columns:
            name = col.get("name")
            is_nullable = col.get("nullable", False)
            has_default = col.get("default") is not None

            if not is_nullable and not has_default:
                violations.append({
                    "column": name,
                    "issue": "New column in expand phase must be nullable or have default to prevent breaking live app",
                })

        compatible = len(violations) == 0
        return {
            "compatible": compatible,
            "violations": violations,
            "can_deploy_without_downtime": compatible,
        }

    # 4. Instant Feature Flag Off-Switch
    def set_feature_flag(self, flag_name: str, enabled: bool):
        self._feature_flags[flag_name] = enabled
        logger.info("feature_flag_toggled", flag=flag_name, enabled=enabled)

    def is_feature_enabled(self, flag_name: str) -> bool:
        return self._feature_flags.get(flag_name, False)

    # 5. Long-Running Job Checkpoint & Handoff
    def checkpoint_job(self, job_id: str, step_name: str, state_data: Dict[str, Any]):
        self._execution_checkpoints[job_id] = {
            "job_id": job_id,
            "last_completed_step": step_name,
            "state_data": state_data,
            "checkpoint_timestamp": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        }

    def resume_job_from_checkpoint(self, job_id: str) -> Optional[Dict[str, Any]]:
        return self._execution_checkpoints.get(job_id)
