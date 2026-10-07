import time
import json
import datetime
from typing import Dict, Any, List, Optional
from pydantic import BaseModel, Field
import structlog
from sqlalchemy.orm import Session

from app.healing.detector import error_detector
from app.models import SupervisorEventModel
from app.database import SessionLocal

logger = structlog.get_logger(__name__)


class SupervisorEvent(BaseModel):
    seq: int
    timestamp: str
    plan_id: str
    execution_id: Optional[int] = None
    phase: str  # "MONITOR", "DETECT", "DECIDE", "ACT", "VERIFY", "AUDIT"
    signature: Optional[str] = None
    diagnosis: Optional[str] = None
    decision: Optional[str] = None
    confidence: float = 1.0
    reasoning: Optional[str] = None
    message: str


class HealingSupervisor:
    """Always-on supervisor watching execution streams in real-time (M-20)."""

    def __init__(self):
        self._events: Dict[str, List[SupervisorEvent]] = {}
        self._seq: Dict[str, int] = {}
        self._last_line_time: Dict[str, float] = {}

    def clear_plan(self, plan_id: str):
        """Reset in-memory event buffers and timers for a plan."""
        self._events.pop(plan_id, None)
        self._seq.pop(plan_id, None)
        self._last_line_time.pop(plan_id, None)

    def _next_seq(self, plan_id: str) -> int:
        self._seq[plan_id] = self._seq.get(plan_id, 0) + 1
        return self._seq[plan_id]

    def emit_event(
        self,
        plan_id: str,
        phase: str,
        message: str,
        signature: Optional[str] = None,
        diagnosis: Optional[str] = None,
        decision: Optional[str] = None,
        confidence: float = 1.0,
        reasoning: Optional[str] = None,
        execution_id: Optional[int] = None,
        db: Optional[Session] = None,
    ) -> SupervisorEvent:
        seq = self._next_seq(plan_id)
        ts = datetime.datetime.utcnow().isoformat()

        event = SupervisorEvent(
            seq=seq,
            timestamp=ts,
            plan_id=plan_id,
            execution_id=execution_id,
            phase=phase,
            signature=signature,
            diagnosis=diagnosis,
            decision=decision,
            confidence=confidence,
            reasoning=reasoning,
            message=message,
        )

        if plan_id not in self._events:
            self._events[plan_id] = []
        self._events[plan_id].append(event)

        active_db = db
        close_db = False
        if active_db is None:
            try:
                active_db = SessionLocal()
                close_db = True
            except Exception:
                active_db = None

        if active_db is not None:
            try:
                model = SupervisorEventModel(
                    plan_id=plan_id,
                    execution_id=execution_id,
                    seq=seq,
                    timestamp=datetime.datetime.utcnow(),
                    phase=phase,
                    signature=signature,
                    diagnosis=diagnosis,
                    decision=decision,
                    confidence=confidence,
                    reasoning=reasoning,
                    message=message,
                )
                active_db.add(model)
                active_db.commit()
            except Exception as e:
                logger.warning("Failed to persist supervisor event", error=str(e), plan_id=plan_id)
            finally:
                if close_db:
                    active_db.close()

        return event

    def on_execution_start(
        self,
        plan_id: str,
        target_env: str,
        region: str,
        execution_id: Optional[int] = None,
        db: Optional[Session] = None,
    ):
        """Called when execution begins."""
        self._last_line_time[plan_id] = time.time()
        self.emit_event(
            plan_id=plan_id,
            phase="MONITOR",
            message=f"Supervisor initialized. Monitoring live execution stream against {target_env.upper()} ({region})...",
            execution_id=execution_id,
            db=db,
        )

    def on_stream_line(
        self,
        plan_id: str,
        line: str,
        attempt: int = 1,
        execution_id: Optional[int] = None,
        db: Optional[Session] = None,
    ) -> Optional[SupervisorEvent]:
        """Scans each output line in real time as it arrives from stdout/stderr."""
        self._last_line_time[plan_id] = time.time()
        detected = error_detector.detect(line)
        if not detected:
            return None

        # 1. Emit DETECT event
        self.emit_event(
            plan_id=plan_id,
            phase="DETECT",
            signature=detected.signature,
            diagnosis=detected.diagnosis,
            confidence=0.98,
            message=f"Detected error pattern [{detected.signature}]: {detected.diagnosis}",
            execution_id=execution_id,
            db=db,
        )

        # 2. Emit DECIDE event based on M-14 safety matrix
        if detected.is_unfixable:
            decision = "unfixable_terminate"
            reasoning = "Unfixable error class (e.g. quota, auth, invalid credentials). Initiating graceful terminate & auto-rollback per policy."
            msg = f"Decision: HALT. Error class '{detected.signature}' is unfixable. Reconcile & rollback per policy."
        elif detected.remediation_class == "approve":
            decision = "awaiting_approval"
            reasoning = "Sensitive modification (e.g. subnet/VPC CIDR recomputation). Human operator approval required."
            msg = f"Decision: PAUSE in HALTED_AWAITING_HUMAN. Proposing remediation for '{detected.signature}'. Human approval required."
        else:
            decision = "playbook_auto_fix"
            reasoning = f"M-14 playbook fix matches signature '{detected.signature}'. Queued for apply attempt {attempt + 1}."
            msg = f"Decision: AUTO-HEAL. Applying playbook fix for '{detected.signature}' and retrying apply."

        decide_event = self.emit_event(
            plan_id=plan_id,
            phase="DECIDE",
            signature=detected.signature,
            diagnosis=detected.diagnosis,
            decision=decision,
            reasoning=reasoning,
            message=msg,
            execution_id=execution_id,
            db=db,
        )
        return decide_event

    def check_stall(self, plan_id: str, max_idle_seconds: float = 180.0) -> bool:
        """Check if execution stream has stalled without output."""
        last_t = self._last_line_time.get(plan_id)
        if not last_t:
            return False
        idle = time.time() - last_t
        if idle > max_idle_seconds:
            self.emit_event(
                plan_id=plan_id,
                phase="MONITOR",
                message=f"⏱️ Stall Detector Alert: No output received for {int(idle)}s. Initiating state probe and zombie check.",
            )
            return True
        return False

    def get_feed(self, plan_id: str, db: Optional[Session] = None) -> List[SupervisorEvent]:
        """Fetch all supervisor events for a plan."""
        if plan_id in self._events and len(self._events[plan_id]) > 0:
            return list(self._events[plan_id])

        active_db = db
        close_db = False
        if active_db is None:
            try:
                active_db = SessionLocal()
                close_db = True
            except Exception:
                active_db = None

        results = []
        if active_db is not None:
            try:
                rows = (
                    active_db.query(SupervisorEventModel)
                    .filter(SupervisorEventModel.plan_id == plan_id)
                    .order_by(SupervisorEventModel.seq.asc())
                    .all()
                )
                for r in rows:
                    results.append(
                        SupervisorEvent(
                            seq=r.seq,
                            timestamp=r.timestamp.isoformat() if r.timestamp else datetime.datetime.utcnow().isoformat(),
                            plan_id=r.plan_id,
                            execution_id=r.execution_id,
                            phase=r.phase,
                            signature=r.signature,
                            diagnosis=r.diagnosis,
                            decision=r.decision,
                            confidence=r.confidence or 1.0,
                            reasoning=r.reasoning,
                            message=r.message,
                        )
                    )
                if results:
                    self._events[plan_id] = list(results)
                    self._seq[plan_id] = max(r.seq for r in results)
            finally:
                if close_db:
                    active_db.close()

        return results

    def clear(self, plan_id: str):
        self._events.pop(plan_id, None)
        self._seq.pop(plan_id, None)
        self._last_line_time.pop(plan_id, None)


healing_supervisor = HealingSupervisor()
