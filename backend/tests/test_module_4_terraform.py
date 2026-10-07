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

    # Check LocalStack endpoint is in the file
    content = (Path(plan_dir) / "main.tf").read_text()
    assert "localhost:4566" in content
    assert "aws_vpc" in content
    assert "aws_s3_bucket" in content
    assert "Vellum" in content
