import json
import pytest
from unittest.mock import MagicMock, patch
from app.healing.kb import RemediationKBManager
from app.healing.engine import SelfHealingEngine
from app.schemas.ir import UniversalIR
from app.schemas.cloud import CloudPlan, CloudResource
from app.database import SessionLocal
from app.models import RemediationKBRecord, PlanRecord

@pytest.fixture
def db_session():
    db = SessionLocal()
    yield db
    db.close()

def test_kb_manager_promotion_after_three_successes(db_session):
    """Test learning loop: after 3 successful identical fixes, promote to deterministic playbook."""
    sig = "TestCustomAttributeMisconfig"
    # Ensure fresh state
    db_session.query(RemediationKBRecord).filter(RemediationKBRecord.signature == sig).delete()
    db_session.commit()

    kb = RemediationKBManager()
    patch_template = {"resources[0].properties.enable_dns_hostnames": True}

    # 1st success
    promoted1 = kb.record_success(signature=sig, fix_type="ir_patch", patch_template=patch_template, db=db_session)
    assert promoted1 is False
    rec1 = kb.get_kb_record(sig, db=db_session)
    assert rec1.success_count == 1
    assert rec1.is_promoted is False

    # 2nd success
    promoted2 = kb.record_success(signature=sig, fix_type="ir_patch", patch_template=patch_template, db=db_session)
    assert promoted2 is False
    rec2 = kb.get_kb_record(sig, db=db_session)
    assert rec2.success_count == 2
    assert rec2.is_promoted is False

    # 3rd success -> PROMOTED!
    promoted3 = kb.record_success(signature=sig, fix_type="ir_patch", patch_template=patch_template, db=db_session)
    assert promoted3 is True
    rec3 = kb.get_kb_record(sig, db=db_session)
    assert rec3.success_count == 3
    assert rec3.is_promoted is True
    assert rec3.version == 2
    assert "promoted" in rec3.description.lower()

def test_fourth_run_heals_with_zero_llm_calls(db_session, tmp_path):
    """4th run for promoted playbook must heal with zero LLM calls."""
    sig = "PromotedAttributeFix"
    db_session.query(RemediationKBRecord).filter(RemediationKBRecord.signature == sig).delete()
    db_session.commit()

    kb = RemediationKBManager()
    patch_template = {"resources[0].properties.enable_dns_hostnames": True}

    # Record 3 successes so it is promoted
    kb.record_success(signature=sig, fix_type="ir_patch", patch_template=patch_template, db=db_session)
    kb.record_success(signature=sig, fix_type="ir_patch", patch_template=patch_template, db=db_session)
    kb.record_success(signature=sig, fix_type="ir_patch", patch_template=patch_template, db=db_session)

    rec = kb.get_kb_record(sig, db=db_session)
    assert rec.is_promoted is True

    # Setup PlanRecord and workspace
    plan_id = "test-plan-promoted-4th"
    db_session.query(PlanRecord).filter(PlanRecord.plan_id == plan_id).delete()
    db_session.commit()

    ir = UniversalIR(
        intent="deploy_cloud",
        cloud=CloudPlan(
            provider="aws",
            region="us-east-1",
            resources=[
                CloudResource(
                    id="vpc_1",
                    name="app_vpc",
                    type="virtual_network",
                    properties={"cidr_block": "10.0.0.0/16"}
                )
            ]
        )
    )

    plan_dir = tmp_path / plan_id
    plan_dir.mkdir(parents=True, exist_ok=True)
    (plan_dir / "main.tf").write_text("resource \"aws_vpc\" \"app_vpc\" {}\n", encoding="utf-8")

    plan_rec = PlanRecord(
        plan_id=plan_id,
        prompt="test",
        ir_json=ir.model_dump_json(),
        terraform_code="resource \"aws_vpc\" \"app_vpc\" {}\n",
        status="running",
        risk_level="low",
    )
    db_session.add(plan_rec)
    db_session.commit()

    # Now run 4th occurrence via SelfHealingEngine
    # Patch llm_fix_proposer so if it is called, it would raise an assertion error
    engine = SelfHealingEngine()

    with patch("app.healing.engine.llm_fix_proposer.propose_fix") as mock_propose:
        # Simulate custom detected error matching our promoted signature
        with patch("app.healing.engine.error_detector.detect") as mock_detect:
            from app.healing.detector import DetectedError
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
                log_text=f"Custom error log for {sig}",
                current_ir=ir,
                plan_dir=str(plan_dir),
                db=db_session,
            )

            # Assert ZERO LLM calls were made!
            mock_propose.assert_not_called()

            # Assert healing was applied deterministically
            assert should_reexec is True
            assert heal_rec is not None
            assert heal_rec.status == "applied"
            assert heal_rec.is_auto_applied is True
            # Verify the patch was applied to IR
            assert patched_ir.cloud.resources[0].properties.get("enable_dns_hostnames") is True
