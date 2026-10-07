import json
import datetime
from typing import List, Dict, Any, Optional
from sqlalchemy.orm import Session
import structlog

from app.models import RemediationKBRecord
from app.database import SessionLocal

logger = structlog.get_logger(__name__)


# Default seeds representing standard taxonomy
DEFAULT_KB_SEEDS = [
    {
        "signature": "BucketAlreadyExists",
        "error_class": "state_conflict",
        "fix_type": "import",
        "description": "Auto-import existing bucket into Terraform state or append safe random suffix.",
        "is_promoted": True,
        "enabled": True,
    },
    {
        "signature": "ResourceNotFound",
        "error_class": "ordering",
        "fix_type": "reorder",
        "description": "Inject explicit depends_on and reorder infrastructure topology in IR.",
        "is_promoted": True,
        "enabled": True,
    },
    {
        "signature": "InvalidSubnet.Range",
        "error_class": "addressing",
        "fix_type": "cidr_recompute",
        "description": "Recompute next non-overlapping CIDR block from VPC allocation table.",
        "is_promoted": True,
        "enabled": True,
    },
    {
        "signature": "HCLSyntaxError",
        "error_class": "generation",
        "fix_type": "regenerate_hcl",
        "description": "Regenerate compliant HCL from Universal IR pre-apply (zero risk).",
        "is_promoted": True,
        "enabled": True,
    },
    {
        "signature": "SQLSyntaxError",
        "error_class": "generation",
        "fix_type": "regenerate_sql",
        "description": "Regenerate dialect-valid SQL DDL schema.",
        "is_promoted": True,
        "enabled": True,
    },
    {
        "signature": "ConnectionRefused",
        "error_class": "transient",
        "fix_type": "retry",
        "description": "Apply exponential backoff with randomized jitter and retry apply.",
        "is_promoted": True,
        "enabled": True,
    },
    {
        "signature": "InvalidParameterValue",
        "error_class": "generation",
        "fix_type": "ir_patch",
        "description": "LLM proposes attribute patch (requires human approval unless in safe whitelist).",
        "is_promoted": False,
        "enabled": True,
    },
    {
        "signature": "InsufficientInstanceCapacity",
        "error_class": "capacity",
        "fix_type": "instance_fallback",
        "description": "Propose fallback compute instance type from capacity tier list.",
        "is_promoted": False,
        "enabled": True,
    },
]


class RemediationKBManager:
    """Manages the remediation knowledge base, learning loop promotions, and circuit breakers."""

    @classmethod
    def seed_defaults(cls, db: Optional[Session] = None) -> None:
        """Seed default knowledge base records if missing."""
        close_db = False
        if db is None:
            db = SessionLocal()
            close_db = True
        try:
            for seed in DEFAULT_KB_SEEDS:
                existing = db.query(RemediationKBRecord).filter(RemediationKBRecord.signature == seed["signature"]).first()
                if not existing:
                    rec = RemediationKBRecord(
                        signature=seed["signature"],
                        error_class=seed["error_class"],
                        fix_type=seed["fix_type"],
                        description=seed["description"],
                        is_promoted=seed["is_promoted"],
                        enabled=seed["enabled"],
                        success_count=5 if seed["is_promoted"] else 0,
                        failure_count=0,
                        cross_plan_failures=0,
                        circuit_broken=False,
                        version=1,
                    )
                    db.add(rec)
            db.commit()
        except Exception as e:
            logger.warning("Error seeding remediation KB", error=str(e))
            db.rollback()
        finally:
            if close_db:
                db.close()

    @classmethod
    def get_kb_record(cls, signature: str, db: Optional[Session] = None) -> Optional[RemediationKBRecord]:
        """Fetch KB record for signature."""
        close_db = False
        if db is None:
            db = SessionLocal()
            close_db = True
        try:
            return db.query(RemediationKBRecord).filter(RemediationKBRecord.signature == signature).first()
        finally:
            if close_db:
                db.close()

    @classmethod
    def list_all(cls, db: Optional[Session] = None) -> List[RemediationKBRecord]:
        """List all KB records."""
        cls.seed_defaults(db=db)
        close_db = False
        if db is None:
            db = SessionLocal()
            close_db = True
        try:
            return db.query(RemediationKBRecord).order_by(RemediationKBRecord.id.asc()).all()
        finally:
            if close_db:
                db.close()

    @classmethod
    def update_record(
        cls,
        rec_id: int,
        enabled: Optional[bool] = None,
        description: Optional[str] = None,
        db: Optional[Session] = None,
    ) -> Optional[RemediationKBRecord]:
        """Update KB record settings."""
        close_db = False
        if db is None:
            db = SessionLocal()
            close_db = True
        try:
            rec = db.query(RemediationKBRecord).filter(RemediationKBRecord.id == rec_id).first()
            if not rec:
                return None
            if enabled is not None:
                rec.enabled = enabled
                if enabled and rec.circuit_broken:
                    rec.circuit_broken = False
                    rec.cross_plan_failures = 0
            if description is not None:
                rec.description = description
            rec.updated_at = datetime.datetime.utcnow()
            db.commit()
            db.refresh(rec)
            return rec
        finally:
            if close_db:
                db.close()

    @classmethod
    def record_success(
        cls,
        signature: str,
        fix_type: str,
        patch_template: Optional[Dict[str, Any]] = None,
        db: Optional[Session] = None,
    ) -> bool:
        """
        Record a successful heal.
        Learning loop rule: If 3 successful identical LLM fixes occur, promote to deterministic playbook!
        """
        close_db = False
        if db is None:
            db = SessionLocal()
            close_db = True
        try:
            rec = db.query(RemediationKBRecord).filter(RemediationKBRecord.signature == signature).first()
            if not rec:
                rec = RemediationKBRecord(
                    signature=signature,
                    error_class="unknown",
                    fix_type=fix_type,
                    description=f"Auto-learned playbook for {signature}",
                    success_count=1,
                    failure_count=0,
                    cross_plan_failures=0,
                    enabled=True,
                    is_promoted=False,
                    circuit_broken=False,
                    version=1,
                    fix_template=json.dumps(patch_template) if patch_template else None,
                )
                db.add(rec)
            else:
                rec.success_count += 1
                rec.cross_plan_failures = 0  # reset cross-plan failure streak on success
                if patch_template and not rec.fix_template:
                    rec.fix_template = json.dumps(patch_template)

                # Promotion check: after 3 successful identical fixes -> promote!
                if not rec.is_promoted and rec.success_count >= 3:
                    rec.is_promoted = True
                    rec.version += 1
                    rec.description = (
                        f"Promoted to deterministic playbook after {rec.success_count} successful identical LLM fixes."
                    )
                    logger.info("Promoted signature to deterministic playbook", signature=signature, count=rec.success_count)

            db.commit()
            return rec.is_promoted
        finally:
            if close_db:
                db.close()

    @classmethod
    def record_failure(
        cls,
        signature: str,
        plan_id: str,
        db: Optional[Session] = None,
    ) -> bool:
        """
        Record a failure for this signature.
        Circuit breaker rule: 3 cross-plan failures -> playbook flagged broken + alert, auto-fix disabled.
        Returns True if circuit breaker was tripped.
        """
        close_db = False
        if db is None:
            db = SessionLocal()
            close_db = True
        try:
            rec = db.query(RemediationKBRecord).filter(RemediationKBRecord.signature == signature).first()
            if not rec:
                rec = RemediationKBRecord(
                    signature=signature,
                    error_class="unknown",
                    fix_type="unknown",
                    description=f"Auto-tracked signature for {signature}",
                    success_count=0,
                    failure_count=1,
                    cross_plan_failures=1,
                    enabled=True,
                    is_promoted=False,
                    circuit_broken=False,
                    version=1,
                )
                db.add(rec)
            else:
                rec.failure_count += 1
                rec.cross_plan_failures += 1

                # Circuit breaker check: 3 cross-plan failures
                if rec.cross_plan_failures >= 3:
                    rec.circuit_broken = True
                    rec.enabled = False
                    logger.warning("Circuit breaker tripped for signature", signature=signature, failures=rec.cross_plan_failures)

            db.commit()
            return rec.circuit_broken
        finally:
            if close_db:
                db.close()


kb_manager = RemediationKBManager()
