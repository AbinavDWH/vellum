import pytest
from app.target import resolve_target, ProductionConnectionRequiredError
from app.models import ConnectionRecord, PlanRecord
from app.schemas.api import ChatRequest
from app.engines.orchestrator import orchestrator
from app.engines.terraform_generator import tf_generator
from app.schemas.ir import UniversalIR
import inspect


def test_target_resolver_connection_conflict(db_session):
    """
    Test Fix 1: If a plan was created against a local connection and you then
    explicitly select prod, resolver must NOT let conn.environment overwrite it.
    It returns an error: 'Plan is bound to a local connection but you selected prod. Re-plan.'
    """
    # Create local connection
    local_conn = ConnectionRecord(
        id="conn_local_bound_plan",
        name="LocalStack Sandbox",
        provider="aws",
        environment="local",
        auth_method="access_key",
        status="connected",
        account_id="000000000000",
    )
    db_session.add(local_conn)
    db_session.commit()

    # Plan bound to this local connection
    plan = PlanRecord(
        plan_id="plan_local_bound_1",
        connection_id="conn_local_bound_plan",
        status="approved",
        prompt="Create S3 bucket",
        intent="create_storage",
        ir_json="{}",
    )
    db_session.add(plan)
    db_session.commit()

    # Resolve with explicit UI choice of 'prod'
    target = resolve_target(plan=plan, environment="prod", db=db_session, strict_prod=False)

    assert target.environment == "prod"
    assert target.is_local is False
    assert target.error == "Plan is bound to a local connection but you selected prod. Re-plan."

    # When strict_prod is True, it must raise ProductionConnectionRequiredError
    with pytest.raises(ProductionConnectionRequiredError) as exc_info:
        resolve_target(plan=plan, environment="prod", db=db_session, strict_prod=True)
    assert "Plan is bound to a local connection but you selected prod. Re-plan." in str(exc_info.value)


def test_dev_environment_protection(db_session):
    """
    Test Fix 2: dev is protected just like prod and staging.
    With no dev connection, dev target is blocked without falling back to host credentials.
    """
    target = resolve_target(environment="dev", db=db_session, strict_prod=False)

    assert target.environment == "dev"
    assert target.is_local is False
    assert target.aws_access_key is None
    assert target.aws_secret_key is None
    assert target.error is not None
    assert "Deployment to 'DEV' is blocked without an active, authenticated AWS connection" in target.error

    with pytest.raises(ProductionConnectionRequiredError) as exc_info:
        resolve_target(environment="dev", db=db_session, strict_prod=True)
    assert "Deployment to 'DEV' is blocked" in str(exc_info.value)


def test_defaults_are_none_and_not_silent_local():
    """
    Test Fix 3: Ensure all identified signatures and schemas default to None,
    not 'local', so missing target check catches them.
    """
    # 1. ChatRequest schema
    assert ChatRequest.model_fields["environment"].default is None

    # 2. orchestrator.process_natural_language
    pnl_sig = inspect.signature(orchestrator.process_natural_language)
    assert pnl_sig.parameters["environment"].default is None

    # 3. orchestrator.plan_from_requirements
    pfr_sig = inspect.signature(orchestrator.plan_from_requirements)
    assert pfr_sig.parameters["environment"].default is None

    # 4. tf_generator.generate
    gen_sig = inspect.signature(tf_generator.generate)
    assert gen_sig.parameters["environment"].default is None

    # 5. Calling tf_generator.generate with no environment and IR without environment raises ValueError
    empty_ir = UniversalIR(intent="empty_plan")
    with pytest.raises(ValueError) as exc:
        tf_generator.generate(empty_ir)
    assert "Target environment is missing" in str(exc.value)
