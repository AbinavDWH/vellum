import pytest
from app.llm.client import llm_client
from app.schemas.ir import UniversalIR


def test_nl_to_ir():
    user_input = """
    I need a student management database with PostgreSQL.
    Students have name, email. They belong to departments.
    Deploy to AWS with a private database.
    """
    ir = llm_client.generate_ir(user_input)

    # Validate structure
    assert isinstance(ir, UniversalIR)
    assert ir.intent in ["create_database", "create_database_and_deploy_cloud", "deploy_cloud"]
    if ir.database:
        assert ir.database.provider == "postgresql"
        assert len(ir.database.tables) >= 1
    if ir.cloud:
        assert ir.cloud.provider == "aws"
