import re
import ipaddress
import time
import random
import subprocess
from pathlib import Path
from typing import Dict, Any, Tuple, Optional, List
import structlog

from app.config import settings
from app.schemas.ir import UniversalIR
from app.healing.detector import DetectedError
from app.engines.terraform_generator import tf_generator

logger = structlog.get_logger(__name__)


class DeterministicPlaybooks:
    """Implementations of whitelisted deterministic self-healing playbooks."""

    @classmethod
    def apply_bucket_already_exists(
        cls,
        detected: DetectedError,
        current_ir: UniversalIR,
        plan_dir: str,
    ) -> Tuple[bool, UniversalIR, str, Dict[str, Any]]:
        """
        Remediation for BucketAlreadyExists:
        1. Try to import existing bucket into Terraform state if localstack is reachable.
        2. Or suffix bucket name in IR and regenerate main.tf.
        """
        bucket_name = detected.metadata.get("bucket_name")
        res_addr = detected.metadata.get("resource_address") or "aws_s3_bucket.main"

        # Check if we can import
        p_dir = Path(plan_dir)
        imported = False
        if bucket_name and p_dir.exists():
            try:
                import_cmd = [settings.TERRAFORM_BINARY, "import", "-no-color", res_addr, bucket_name]
                res = subprocess.run(import_cmd, cwd=str(p_dir), capture_output=True, text=True, timeout=30)
                if res.returncode == 0:
                    imported = True
                    logger.info("Successfully imported S3 bucket into terraform state", bucket=bucket_name)
            except Exception as e:
                logger.warning("Terraform import notice", error=str(e))

        # If import succeeded, keep same IR, return success
        if imported:
            diff = {
                "action": "import",
                "resource": res_addr,
                "target_id": bucket_name,
                "reasoning": f"Imported existing bucket [{bucket_name}] into Terraform state.",
            }
            main_tf = (p_dir / "main.tf").read_text(encoding="utf-8") if (p_dir / "main.tf").exists() else ""
            return True, current_ir, main_tf, diff

        # Fallback: Suffix bucket name in IR to ensure uniqueness
        ir_dict = current_ir.model_dump()
        suffix = f"-{random.randint(1000, 9999)}"
        new_bucket_name = f"{bucket_name or 'vellum-storage'}{suffix}"

        if ir_dict.get("cloud") and ir_dict["cloud"].get("resources"):
            for res in ir_dict["cloud"]["resources"]:
                if res.get("type") == "object_storage":
                    old_name = res.get("name")
                    res["properties"]["bucket"] = new_bucket_name
                    res["properties"]["bucket_name"] = new_bucket_name
                    break

        patched_ir = UniversalIR(**ir_dict)
        real_env = (patched_ir.cloud.environment if patched_ir.cloud and patched_ir.cloud.environment else "local")
        tf_generator.generate(patched_ir, environment=real_env, plan_id=Path(plan_dir).name)
        new_hcl = (p_dir / "main.tf").read_text(encoding="utf-8") if (p_dir / "main.tf").exists() else ""

        diff = {
            "action": "suffix_name",
            "resource": res_addr,
            "old_name": bucket_name,
            "new_name": new_bucket_name,
            "reasoning": f"Suffixed S3 bucket name to [{new_bucket_name}] to eliminate global naming conflict.",
        }
        return True, patched_ir, new_hcl, diff

    @classmethod
    def apply_cidr_recompute(
        cls,
        detected: DetectedError,
        current_ir: UniversalIR,
        plan_dir: str,
    ) -> Tuple[bool, UniversalIR, str, Dict[str, Any]]:
        """
        Remediation for InvalidSubnet.Range / CIDR overlap:
        Recomputes the next free non-overlapping CIDR block from VPC state.
        """
        ir_dict = current_ir.model_dump()
        p_dir = Path(plan_dir)

        # Find existing subnet CIDRs and VPC CIDR
        vpc_cidr_str = "10.0.0.0/16"
        used_cidrs = set()

        if ir_dict.get("cloud") and ir_dict["cloud"].get("resources"):
            for res in ir_dict["cloud"]["resources"]:
                if res.get("type") == "virtual_network":
                    vpc_cidr_str = res.get("properties", {}).get("cidr_block", vpc_cidr_str)
                elif res.get("type") == "subnet":
                    c = res.get("properties", {}).get("cidr_block")
                    if c:
                        used_cidrs.add(c)

        # Compute next free /24 subnet in VPC
        try:
            vpc_net = ipaddress.ip_network(vpc_cidr_str)
            subnets = list(vpc_net.subnets(new_prefix=24))
        except Exception:
            subnets = [ipaddress.ip_network(f"10.0.{i}.0/24") for i in range(1, 20)]

        conflicting = detected.metadata.get("conflicting_cidr")
        if conflicting:
            used_cidrs.add(conflicting)

        free_subnet = None
        for s in subnets:
            s_str = str(s)
            if s_str not in used_cidrs:
                free_subnet = s_str
                break

        if not free_subnet:
            free_subnet = "10.0.99.0/24"

        # Update overlapping subnet in IR
        changed_res = None
        old_cidr = ""
        target_subnet_idx = None
        seen_cidrs = set()

        if ir_dict.get("cloud") and ir_dict["cloud"].get("resources"):
            # First pass: check if any subnet has a duplicate CIDR of a prior subnet
            for idx, res in enumerate(ir_dict["cloud"]["resources"]):
                if res.get("type") == "subnet":
                    c = res.get("properties", {}).get("cidr_block")
                    if c in seen_cidrs:
                        target_subnet_idx = idx
                        break
                    seen_cidrs.add(c)

            # If no duplicate found, check if a subnet matches conflicting_cidr or choose the first subnet
            if target_subnet_idx is None:
                for idx, res in enumerate(ir_dict["cloud"]["resources"]):
                    if res.get("type") == "subnet":
                        if conflicting and res.get("properties", {}).get("cidr_block") == conflicting:
                            target_subnet_idx = idx
                            break
                        if target_subnet_idx is None:
                            target_subnet_idx = idx

            if target_subnet_idx is not None:
                res = ir_dict["cloud"]["resources"][target_subnet_idx]
                old_cidr = res.get("properties", {}).get("cidr_block", "")
                res["properties"]["cidr_block"] = free_subnet
                changed_res = res.get("name")

        patched_ir = UniversalIR(**ir_dict)
        real_env = (patched_ir.cloud.environment if patched_ir.cloud and patched_ir.cloud.environment else "local")
        tf_generator.generate(patched_ir, environment=real_env, plan_id=Path(plan_dir).name)
        new_hcl = (p_dir / "main.tf").read_text(encoding="utf-8") if (p_dir / "main.tf").exists() else ""

        diff = {
            "action": "recompute_cidr",
            "resource": changed_res,
            "old_cidr": old_cidr,
            "new_cidr": free_subnet,
            "reasoning": f"Recomputed next available CIDR block [{free_subnet}] inside VPC [{vpc_cidr_str}] avoiding collisions.",
        }
        return True, patched_ir, new_hcl, diff

    @classmethod
    def apply_dependency_ordering(
        cls,
        detected: DetectedError,
        current_ir: UniversalIR,
        plan_dir: str,
    ) -> Tuple[bool, UniversalIR, str, Dict[str, Any]]:
        """
        Remediation for ResourceNotFound (ordering):
        Injects explicit depends_on and ensures network resources precede dependent resources.
        """
        ir_dict = current_ir.model_dump()
        p_dir = Path(plan_dir)

        # Sort resources so virtual_network comes first, then subnet, then security groups, then instances/db
        order_weights = {
            "virtual_network": 1,
            "subnet": 2,
            "security_rule": 3,
            "object_storage": 4,
            "managed_database": 5,
            "compute_instance": 6,
        }

        if ir_dict.get("cloud") and ir_dict["cloud"].get("resources"):
            res_list = ir_dict["cloud"]["resources"]
            res_list.sort(key=lambda r: order_weights.get(r.get("type"), 10))

            # Find VPC name
            vpc_names = [r.get("name") for r in res_list if r.get("type") == "virtual_network"]
            vpc_name = vpc_names[0] if vpc_names else None

            # Add dependency to subnets
            for r in res_list:
                if r.get("type") in ["subnet", "security_rule", "managed_database"] and vpc_name:
                    deps = r.setdefault("depends_on", [])
                    if vpc_name not in deps:
                        deps.append(vpc_name)

        patched_ir = UniversalIR(**ir_dict)
        real_env = (patched_ir.cloud.environment if patched_ir.cloud and patched_ir.cloud.environment else "local")
        tf_generator.generate(patched_ir, environment=real_env, plan_id=Path(plan_dir).name)
        new_hcl = (p_dir / "main.tf").read_text(encoding="utf-8") if (p_dir / "main.tf").exists() else ""

        diff = {
            "action": "reorder_dependencies",
            "reasoning": "Reordered resource topology in IR and added explicit depends_on references to eliminate dependency race condition.",
        }
        return True, patched_ir, new_hcl, diff

    @classmethod
    def apply_regenerate_hcl(
        cls,
        detected: DetectedError,
        current_ir: UniversalIR,
        plan_dir: str,
    ) -> Tuple[bool, UniversalIR, str, Dict[str, Any]]:
        """
        Remediation for HCLSyntaxError:
        Regenerate clean HCL from the Universal IR.
        """
        p_dir = Path(plan_dir)
        real_env = (current_ir.cloud.environment if current_ir.cloud and current_ir.cloud.environment else "local")
        tf_generator.generate(current_ir, environment=real_env, plan_id=p_dir.name)
        new_hcl = (p_dir / "main.tf").read_text(encoding="utf-8") if (p_dir / "main.tf").exists() else ""

        diff = {
            "action": "regenerate_hcl",
            "reasoning": "Regenerated pure HCL formatting from the Universal IR to eliminate syntax and block definition errors.",
        }
        return True, current_ir, new_hcl, diff

    @classmethod
    def apply_regenerate_sql(
        cls,
        detected: DetectedError,
        current_ir: UniversalIR,
        plan_dir: str,
    ) -> Tuple[bool, UniversalIR, str, Dict[str, Any]]:
        """
        Remediation for SQLSyntaxError:
        Regenerate DDL using appropriate database adapter.
        """
        from app.adapters.database.base import get_database_adapter
        new_sql = ""
        if current_ir.database:
            adapter = get_database_adapter(current_ir.database.provider)
            new_sql = adapter.generate_ddl(current_ir.database)

        diff = {
            "action": "regenerate_sql",
            "reasoning": "Regenerated SQL DDL with dialect-specific schema validation.",
        }
        return True, current_ir, new_sql, diff

    @classmethod
    def apply_transient_retry(
        cls,
        attempt: int,
    ) -> float:
        """
        Exponential backoff with jitter for transient connection errors.
        """
        delay = min(2 ** (attempt - 1) + random.uniform(0.1, 0.5), 8.0)
        logger.info("Applying exponential backoff for transient error", attempt=attempt, delay=delay)
        time.sleep(delay)
        return delay

    @classmethod
    def apply_instance_fallback(
        cls,
        detected: DetectedError,
        current_ir: UniversalIR,
        plan_dir: str,
    ) -> Tuple[bool, UniversalIR, str, Dict[str, Any]]:
        """
        Remediation for InsufficientInstanceCapacity:
        Switch to fallback instance class in instance hierarchy.
        """
        FALLBACK_MAP = {
            "t3.xlarge": "t3a.xlarge",
            "t3.large": "t3a.large",
            "t3.medium": "t3a.medium",
            "t3a.medium": "t3.small",
            "t3.small": "t2.small",
            "t2.small": "t3.micro",
            "t3.micro": "t2.micro",
        }

        ir_dict = current_ir.model_dump()
        p_dir = Path(plan_dir)
        old_inst = detected.metadata.get("requested_type") or "t3.small"
        new_inst = FALLBACK_MAP.get(old_inst, "t3.micro")

        if ir_dict.get("cloud") and ir_dict["cloud"].get("resources"):
            for res in ir_dict["cloud"]["resources"]:
                if res.get("type") == "compute_instance":
                    res["properties"]["instance_type"] = new_inst

        patched_ir = UniversalIR(**ir_dict)
        real_env = (patched_ir.cloud.environment if patched_ir.cloud and patched_ir.cloud.environment else "local")
        tf_generator.generate(patched_ir, environment=real_env, plan_id=Path(plan_dir).name)
        new_hcl = (p_dir / "main.tf").read_text(encoding="utf-8") if (p_dir / "main.tf").exists() else ""

        diff = {
            "action": "instance_fallback",
            "old_instance_type": old_inst,
            "new_instance_type": new_inst,
            "reasoning": f"Switched compute instance type from [{old_inst}] to fallback type [{new_inst}] due to provider capacity limits.",
        }
        return True, patched_ir, new_hcl, diff


playbooks = DeterministicPlaybooks()
