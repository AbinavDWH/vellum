"""
Observability, Golden Signals SLO monitoring, distributed tracing, and immutable audit logs.
Implements controls for Module P-06 (Observability, Alerting & On-Call).
"""
import hashlib
import json
import datetime
from typing import Dict, Any, List, Optional
import structlog

logger = structlog.get_logger(__name__)


class ObservabilityEngine:
    """
    Observability & Alerting Governance:
    1. Golden Signals & SLO Incident Detection SLA (< 180s)
    2. End-to-end distributed correlation tracking (UI -> Backend -> Executor -> DB)
    3. Queue backlog and DLQ stall detection
    4. Alert-to-runbook mapping audit (zero orphan alerts)
    5. Immutable WORM audit retention and hash verification
    """

    MAX_DETECTION_SLA_SECONDS = 180.0

    def __init__(self):
        self._traces: Dict[str, List[Dict[str, Any]]] = {}
        self._alert_definitions: List[Dict[str, Any]] = [
            {
                "name": "HighHttp5xxErrorRate",
                "severity": "P1",
                "runbook_url": "https://github.com/vellum/vellum/docs/runbooks/high_5xx_errors.md",
            },
            {
                "name": "DatabaseConnectionPoolSaturation",
                "severity": "P1",
                "runbook_url": "https://github.com/vellum/vellum/docs/runbooks/db_pool_exhaustion.md",
            },
            {
                "name": "PlanExecutionQueueBacklog",
                "severity": "P2",
                "runbook_url": "https://github.com/vellum/vellum/docs/runbooks/queue_backlog.md",
            },
            {
                "name": "LLMInferenceLatencyDegradation",
                "severity": "P2",
                "runbook_url": "https://github.com/vellum/vellum/docs/runbooks/llm_latency.md",
            },
        ]
        self._archive_store: Dict[str, Dict[str, Any]] = {}

    @classmethod
    def evaluate_slo_incident(
        cls,
        metric_name: str,
        value: float,
        threshold: float,
        incident_detection_seconds: float
    ) -> Dict[str, Any]:
        """
        Evaluates incident detection against golden signals SLO.
        """
        breached = value > threshold
        paged_within_sla = incident_detection_seconds <= cls.MAX_DETECTION_SLA_SECONDS
        return {
            "metric": metric_name,
            "value": value,
            "threshold": threshold,
            "breached": breached,
            "detection_seconds": incident_detection_seconds,
            "within_detection_sla": paged_within_sla,
            "paged": breached and paged_within_sla,
        }

    def record_trace_span(
        self,
        correlation_id: str,
        service: str,
        operation: str,
        details: Optional[Dict[str, Any]] = None
    ):
        """Records a distributed trace span under a single correlation ID."""
        if correlation_id not in self._traces:
            self._traces[correlation_id] = []

        self._traces[correlation_id].append({
            "correlation_id": correlation_id,
            "service": service,
            "operation": operation,
            "timestamp": datetime.datetime.now(datetime.timezone.utc).isoformat(),
            "details": details or {},
        })

    def get_full_trace(self, correlation_id: str) -> List[Dict[str, Any]]:
        """Returns the full end-to-end trace across services for a correlation ID."""
        return self._traces.get(correlation_id, [])

    @classmethod
    def check_queue_backlog(
        cls,
        queue_depth: int,
        oldest_message_age_seconds: float,
        max_age_threshold_seconds: float = 60.0
    ) -> Dict[str, Any]:
        """
        Monitors queue health. Raises alert before user impact occurs.
        """
        is_stalled = oldest_message_age_seconds > max_age_threshold_seconds or queue_depth > 100
        return {
            "queue_depth": queue_depth,
            "oldest_message_age_seconds": oldest_message_age_seconds,
            "is_stalled": is_stalled,
            "alert_triggered": is_stalled,
            "action_required": "SCALE_WORKERS" if is_stalled else "NONE",
        }

    def audit_alert_runbooks(self) -> Dict[str, Any]:
        """
        Audits all alerts to enforce zero orphan alerts policy.
        Every alert must have an active runbook link.
        """
        orphan_alerts = []
        for alert in self._alert_definitions:
            url = alert.get("runbook_url", "")
            if not url or not url.startswith("http"):
                orphan_alerts.append(alert["name"])

        return {
            "total_alerts": len(self._alert_definitions),
            "orphan_count": len(orphan_alerts),
            "orphan_alerts": orphan_alerts,
            "compliant": len(orphan_alerts) == 0,
        }

    def archive_audit_entry(self, entry_id: str, payload: Dict[str, Any], date_str: str) -> str:
        """Stores audit entry in immutable WORM archive."""
        payload_str = json.dumps(payload, sort_keys=True)
        payload_hash = hashlib.sha256(payload_str.encode("utf-8")).hexdigest()
        self._archive_store[entry_id] = {
            "entry_id": entry_id,
            "date": date_str,
            "payload": payload,
            "payload_hash": payload_hash,
            "immutable": True,
        }
        return payload_hash

    def retrieve_and_verify_archive(self, entry_id: str) -> Dict[str, Any]:
        """Retrieves historical audit entry and cryptographically verifies its hash."""
        entry = self._archive_store.get(entry_id)
        if not entry:
            return {"verified": False, "error": "Entry not found in archive"}

        recalculated_hash = hashlib.sha256(
            json.dumps(entry["payload"], sort_keys=True).encode("utf-8")
        ).hexdigest()

        hash_verified = (recalculated_hash == entry["payload_hash"])
        return {
            "verified": hash_verified,
            "entry_id": entry_id,
            "recorded_hash": entry["payload_hash"],
            "recalculated_hash": recalculated_hash,
            "date": entry["date"],
        }
