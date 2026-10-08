import os
import subprocess
import uuid
from pathlib import Path
from typing import Dict, Any, Union, Optional
from app.config import settings
from app.adapters.cloud.aws import AWSAdapter
from app.adapters.cloud.azure import AzureAdapter
from app.schemas.ir import UniversalIR


class TerraformGenerator:
    """Generates provider-specific Terraform HCL code and workspace structures."""

    def __init__(self, workspace_root: Optional[str] = None):
        self.workspace_root = Path(workspace_root or settings.TERRAFORM_WORKSPACE)
        self.workspace_root.mkdir(parents=True, exist_ok=True)
        self.adapters = {
            "aws": AWSAdapter(),
            "azure": AzureAdapter(),
        }

    def _get_adapter(self, provider_name: str):
        adapter = self.adapters.get(provider_name.lower())
        if not adapter:
            raise ValueError(f"Unsupported cloud provider: '{provider_name}'")
        return adapter

    def generate(
        self,
        ir: Union[dict, UniversalIR],
        environment: Optional[str] = None,
        plan_id: Optional[str] = None,
    ) -> str:
        """
        Generate Terraform files in a dedicated workspace directory.
        Returns the absolute path to the workspace directory.
        """
        from app.target import resolve_target

        target = resolve_target(ir=ir, environment=environment, allow_missing=False)
        if target.error and "Plan is bound to a" in target.error:
            raise ValueError(target.error)
        environment = target.environment

        if isinstance(ir, UniversalIR):
            ir_dict = ir.model_dump()
        else:
            ir_dict = ir

        cloud = ir_dict.get("cloud")
        if not cloud:
            # If no cloud defined in IR, create empty or default AWS plan
            cloud = {"provider": "aws", "region": "us-east-1", "resources": []}
            ir_dict["cloud"] = cloud

        provider = cloud.get("provider", "aws")
        adapter = self._get_adapter(provider)

        # 1. Map resources
        mapped = adapter.map_resources(ir_dict)

        # 2. Generate HCL
        region = target.region or cloud.get("region") or settings.LOCALSTACK_REGION or "us-east-1"
        if provider == "aws":
            hcl_content = adapter.generate_terraform(mapped, environment=environment, region=region)
        else:
            hcl_content = adapter.generate_terraform(mapped, environment=environment)

        # 3. Write to workspace
        folder_name = plan_id or f"plan_{uuid.uuid4().hex[:8]}"
        plan_dir = self.workspace_root / folder_name
        plan_dir.mkdir(parents=True, exist_ok=True)

        main_tf_path = plan_dir / "main.tf"
        main_tf_path.write_text(hcl_content, encoding="utf-8")

        # 4. Generate executable deployment script (deploy.sh)
        deploy_sh_path = plan_dir / "deploy.sh"
        deploy_sh_content = f"""#!/usr/bin/env bash
# ========================================================
# Vellum Autonomous Infrastructure Deployment Script
# Target: {provider.upper()} ({environment.upper()})
# ========================================================
set -euo pipefail

echo "==> Initializing Terraform in $(pwd)..."
terraform init -upgrade

echo "==> Validating configuration..."
terraform validate

echo "==> Planning deployment..."
terraform plan -out=tfplan

echo "==> Applying infrastructure changes..."
terraform apply -auto-approve tfplan

echo "==> Infrastructure deployment completed successfully!"
terraform output
"""
        deploy_sh_path.write_text(deploy_sh_content, encoding="utf-8")
        try:
            deploy_sh_path.chmod(0o755)
        except Exception:
            pass

        # Format if terraform binary exists
        try:
            subprocess.run(
                [settings.TERRAFORM_BINARY, "fmt"],
                cwd=str(plan_dir),
                capture_output=True,
                timeout=5,
            )
        except Exception:
            pass

        return str(plan_dir.resolve())

    def validate(self, plan_dir: str) -> tuple[bool, str]:
        """Runs terraform init and terraform validate."""
        try:
            init_res = subprocess.run(
                [settings.TERRAFORM_BINARY, "init", "-backend=false"],
                cwd=plan_dir,
                capture_output=True,
                text=True,
                timeout=30,
            )
            if init_res.returncode != 0:
                return False, f"Terraform init failed: {init_res.stderr or init_res.stdout}"

            val_res = subprocess.run(
                [settings.TERRAFORM_BINARY, "validate"],
                cwd=plan_dir,
                capture_output=True,
                text=True,
                timeout=15,
            )
            return val_res.returncode == 0, val_res.stdout or val_res.stderr
        except Exception as e:
            return False, str(e)


tf_generator = TerraformGenerator()
