import pytest
from unittest.mock import MagicMock, patch
from app.healing.engine import SelfHealingEngine
from app.schemas.ir import UniversalIR
from app.schemas.cloud import CloudPlan, CloudResource
from app.models import HealingAttemptRecord
from app.database import get_db, SessionLocal

@pytest.fixture
def db_session():
    db = SessionLocal()
    yield db
    db.close()

def test_loop_cap_stops_at_max_three_attempts(db_session):
    """Force persistent failure: stops at attempt 3 with diagnosis (no infinite loop)."""
    engine = SelfHealingEngine()
    plan_id = "test-plan-loop-cap-1"
    ir = UniversalIR(
        intent="deploy_cloud",
        cloud=CloudPlan(
            provider="aws",
            region="us-east-1",
            resources=[
                CloudResource(
                    id="r1",
                    name="subnet_1",
                    type="subnet",
                    properties={"cidr_block": "10.0.1.0/24"}
                )
            ]
        )
    )

    persistent_error_log = "Error: creating EC2 Subnet: InvalidSubnet.Range: The CIDR '10.0.1.0/24' conflicts with another subnet"

    # Attempt 1: auto-heals and allows re-execute
    should_reexec1, ir1, _, det1, rec1 = engine.evaluate_and_heal(
        plan_id=plan_id,
        execution_id=None,
        attempt_number=1,
        log_text=persistent_error_log,
        current_ir=ir,
        plan_dir="/tmp",
        db=db_session
    )
    assert should_reexec1 is True
    assert det1.signature == "InvalidSubnet.Range"
    assert rec1.status == "applied"

    # Attempt 2: auto-heals and allows re-execute
    should_reexec2, ir2, _, det2, rec2 = engine.evaluate_and_heal(
        plan_id=plan_id,
        execution_id=None,
        attempt_number=2,
        log_text=persistent_error_log,
        current_ir=ir1 or ir,
        plan_dir="/tmp",
        db=db_session
    )
    assert should_reexec2 is True
    assert rec2.status == "applied"

    # Attempt 3: auto-heals and allows re-execute
    should_reexec3, ir3, _, det3, rec3 = engine.evaluate_and_heal(
        plan_id=plan_id,
        execution_id=None,
        attempt_number=3,
        log_text=persistent_error_log,
        current_ir=ir2 or ir,
        plan_dir="/tmp",
        db=db_session
    )
    assert should_reexec3 is True
    assert rec3.status == "applied"

    # Attempt 4: Loop cap hit! Must halt, return should_reexecute=False, status="halted", clean diagnosis
    events = []
    def capture_event(ev):
        events.append(ev)

    should_reexec4, ir4, _, det4, rec4 = engine.evaluate_and_heal(
        plan_id=plan_id,
        execution_id=None,
        attempt_number=4,
        log_text=persistent_error_log,
        current_ir=ir3 or ir,
        plan_dir="/tmp",
        on_event=capture_event,
        db=db_session
    )

    assert should_reexec4 is False
    assert ir4 is None
    assert rec4 is not None
    assert rec4.status == "halted"
    assert "loop cap" in rec4.reasoning.lower() or "exhausted" in rec4.reasoning.lower()

    # Verify event emitted
    halted_events = [e for e in events if e.get("event") == "heal_halted"]
    assert len(halted_events) >= 1
    assert halted_events[0]["reason"] == "loop_cap_reached"
