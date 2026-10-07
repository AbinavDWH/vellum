import pytest
from app.healing.kb import RemediationKBManager
from app.healing.engine import SelfHealingEngine
from app.schemas.ir import UniversalIR
from app.schemas.cloud import CloudPlan, CloudResource
from app.database import SessionLocal
from app.models import RemediationKBRecord

@pytest.fixture
def db_session():
    db = SessionLocal()
    yield db
    db.close()

def test_circuit_breaker_trips_after_three_cross_plan_failures(db_session):
    sig = "TestFragileSignature"
    db_session.query(RemediationKBRecord).filter(RemediationKBRecord.signature == sig).delete()
    db_session.commit()

    kb = RemediationKBManager()

    # Fail across 3 different plans
    tripped1 = kb.record_failure(sig, plan_id="plan-1", db=db_session)
    assert tripped1 is False
    rec1 = kb.get_kb_record(sig, db=db_session)
    assert rec1.cross_plan_failures == 1
    assert rec1.circuit_broken is False
    assert rec1.enabled is True

    tripped2 = kb.record_failure(sig, plan_id="plan-2", db=db_session)
    assert tripped2 is False
    rec2 = kb.get_kb_record(sig, db=db_session)
    assert rec2.cross_plan_failures == 2
    assert rec2.circuit_broken is False

    # 3rd failure -> Trips circuit breaker!
    tripped3 = kb.record_failure(sig, plan_id="plan-3", db=db_session)
    assert tripped3 is True
    rec3 = kb.get_kb_record(sig, db=db_session)
    assert rec3.cross_plan_failures == 3
    assert rec3.circuit_broken is True
    assert rec3.enabled is False

def test_circuit_broken_playbook_blocks_auto_fix(db_session, tmp_path):
    """When circuit breaker is active, auto-remediation is disabled and requires human approval."""
    sig = "BrokenPlaybookSig"
    db_session.query(RemediationKBRecord).filter(RemediationKBRecord.signature == sig).delete()
    db_session.commit()

    kb = RemediationKBManager()
    # Trip circuit breaker
    kb.record_failure(sig, plan_id="p1", db=db_session)
    kb.record_failure(sig, plan_id="p2", db=db_session)
    kb.record_failure(sig, plan_id="p3", db=db_session)

    rec = kb.get_kb_record(sig, db=db_session)
    assert rec.circuit_broken is True

    engine = SelfHealingEngine()
    plan_id = "test-plan-cb-active"

    ir = UniversalIR(
        intent="deploy_cloud",
        cloud=CloudPlan(
            provider="aws",
            region="us-east-1",
            resources=[]
        )
    )

    from unittest.mock import patch
    from app.healing.detector import DetectedError

    with patch("app.healing.engine.error_detector.detect") as mock_detect:
        mock_detect.return_value = DetectedError(
            signature=sig,
            error_class="generation",
            message=f"Error matching {sig}",
            is_unfixable=False,
        )

        should_reexec, patched_ir, _, detected, heal_rec = engine.evaluate_and_heal(
            plan_id=plan_id,
            execution_id=None,
            attempt_number=1,
            log_text=f"Error {sig}",
            current_ir=ir,
            plan_dir=str(tmp_path),
            db=db_session,
        )

        # Must NOT auto-apply!
        assert should_reexec is False
        assert heal_rec is not None
        assert heal_rec.status == "awaiting_approval"
        assert heal_rec.remediation_class == "approve"
        assert "circuit breaker active" in heal_rec.reasoning.lower()

def test_circuit_breaker_reset_on_re_enable(db_session):
    sig = "ResetCircuitSig"
    db_session.query(RemediationKBRecord).filter(RemediationKBRecord.signature == sig).delete()
    db_session.commit()

    kb = RemediationKBManager()
    kb.record_failure(sig, plan_id="p1", db=db_session)
    kb.record_failure(sig, plan_id="p2", db=db_session)
    kb.record_failure(sig, plan_id="p3", db=db_session)

    rec = kb.get_kb_record(sig, db=db_session)
    assert rec.circuit_broken is True

    # User re-enables in UI/Settings
    updated = kb.update_record(rec_id=rec.id, enabled=True, db=db_session)
    assert updated.enabled is True
    assert updated.circuit_broken is False
    assert updated.cross_plan_failures == 0
