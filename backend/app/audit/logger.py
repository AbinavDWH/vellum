import hashlib
import json
import datetime
from typing import Dict, Any, List, Optional
from sqlalchemy.orm import Session
from app.models import AuditLogRecord
from app.database import SessionLocal


class AuditLogger:
    """Immutable audit trail for all infrastructure actions and human approvals."""

    def __init__(self):
        self._memory_logs: List[Dict[str, Any]] = []

    def log(
        self,
        event_type: str,
        plan_id: Optional[str] = None,
        risk_level: str = "low",
        action_by: str = "system",
        details: Optional[Dict[str, Any]] = None,
        db: Optional[Session] = None,
    ) -> Dict[str, Any]:
        details = details or {}
        payload_str = json.dumps(details, sort_keys=True, default=str)
        payload_hash = hashlib.sha256(payload_str.encode("utf-8")).hexdigest()
        now = datetime.datetime.utcnow()

        entry = {
            "event_type": event_type,
            "plan_id": plan_id,
            "risk_level": risk_level,
            "action_by": action_by,
            "payload_hash": payload_hash,
            "details": details,
            "timestamp": now.isoformat(),
        }
        self._memory_logs.append(entry)

        # Persist to database
        close_session = False
        if db is None:
            db = SessionLocal()
            close_session = True

        try:
            record = AuditLogRecord(
                plan_id=plan_id,
                event_type=event_type,
                risk_level=risk_level,
                action_by=action_by,
                payload_hash=payload_hash,
                details_json=payload_str,
                timestamp=now,
            )
            db.add(record)
            db.commit()
        except Exception:
            db.rollback()
        finally:
            if close_session:
                db.close()

        return entry

    def get_log(self, plan_id: str) -> Optional[Dict[str, Any]]:
        """Fetch audit log for a given plan."""
        matches = [m for m in self._memory_logs if m.get("plan_id") == plan_id]
        if matches:
            return matches[-1]
        
        # Check DB
        db = SessionLocal()
        try:
            record = db.query(AuditLogRecord).filter(AuditLogRecord.plan_id == plan_id).order_by(AuditLogRecord.id.desc()).first()
            if record:
                return {
                    "event_type": record.event_type,
                    "plan_id": record.plan_id,
                    "risk_level": record.risk_level,
                    "action_by": record.action_by,
                    "payload_hash": record.payload_hash,
                    "details": json.loads(record.details_json),
                    "timestamp": record.timestamp.isoformat(),
                }
        finally:
            db.close()

        return None

    def get_all_logs(self, limit: int = 50) -> List[Dict[str, Any]]:
        db = SessionLocal()
        try:
            records = db.query(AuditLogRecord).order_by(AuditLogRecord.id.desc()).limit(limit).all()
            if records:
                return [{
                    "id": r.id,
                    "event_type": r.event_type,
                    "plan_id": r.plan_id,
                    "risk_level": r.risk_level,
                    "action_by": r.action_by,
                    "payload_hash": r.payload_hash,
                    "details": json.loads(r.details_json),
                    "timestamp": r.timestamp.isoformat(),
                } for r in records]
        except Exception:
            pass
        finally:
            db.close()

        return self._memory_logs[-limit:]


audit_logger = AuditLogger()
