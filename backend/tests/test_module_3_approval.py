import pytest
from app.approval.engine import ApprovalEngine
from app.validation.policy import RiskLevel


def test_approval_gate_blocks_execution():
    plan = {
        "intent": "create_database_and_deploy_cloud",
        "database": {
            "provider": "postgresql",
            "database_name": "students_db",
            "tables": [
                {
                    "name": "students",
                    "columns": [
                        {"name": "id", "data_type": "serial", "primary_key": True},
                        {"name": "name", "data_type": "varchar(255)"},
                    ],
                }
            ],
        },
        "cloud": {
            "provider": "aws",
            "region": "us-east-1",
            "resources": [
                {"type": "virtual_network", "name": "main_vpc", "properties": {"cidr_block": "10.0.0.0/16"}}
            ],
        },
    }
    engine = ApprovalEngine()

    assert engine.requires_approval(plan) is True

    risk = engine.classify_risk(plan)
    assert risk == RiskLevel.MEDIUM

    preview = engine.format_plan_preview(plan)
    assert "APPROVE" in preview
    assert "CREATE TABLE" in preview
