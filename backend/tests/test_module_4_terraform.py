import pytest
from pathlib import Path
from app.engines.terraform_generator import TerraformGenerator


def test_terraform_generation():
    ir = {
        "cloud": {
            "provider": "aws",
            "region": "us-east-1",
            "resources": [
                {"type": "virtual_network", "name": "test_vpc", "properties": {"cidr_block": "10.0.0.0/16"}},
                {"type": "object_storage", "name": "test-bucket", "properties": {}},
            ],
        }
    }

    generator = TerraformGenerator()
    plan_dir = generator.generate(ir, environment="local")

    # Check file exists
    assert (Path(plan_dir) / "main.tf").exists()

    # Verify standard AWS Cloud provider configuration (no LocalStack endpoint overrides)
    content = (Path(plan_dir) / "main.tf").read_text()
    assert 'provider "aws"' in content
    assert "localhost:4566" not in content
    assert "aws_vpc" in content
    assert "aws_s3_bucket" in content
    assert "Vellum" in content
