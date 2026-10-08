import pytest
from app.engines.terraform_generator import TerraformGenerator
from app.engines.execution_engine import ExecutionEngine


def test_execution_against_localstack():
    test_ir = {
        "cloud": {
            "provider": "aws",
            "region": "us-east-1",
            "environment": "local",
            "resources": [
                {"type": "object_storage", "name": "test-bucket", "properties": {"bucket_name": "vellum-test-exec-bucket"}}
            ],
        }
    }

    generator = TerraformGenerator()
    plan_dir = generator.generate(test_ir, environment="local")

    engine = ExecutionEngine()
    result = engine.execute_plan(plan_dir, plan_id="test_001")

    assert result.success is True
    assert result.resources_created > 0
