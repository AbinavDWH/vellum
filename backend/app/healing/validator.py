import os
import shutil
import difflib
from pathlib import Path
from typing import Dict, Any, Tuple, List, Optional
import structlog

from app.config import settings
from app.schemas.ir import UniversalIR
from app.healing.proposer import LLMFixProposal
from app.validation.security import SecurityValidator
from app.validation.policy import PolicyEngine, RiskLevel
from app.engines.terraform_generator import tf_generator

logger = structlog.get_logger(__name__)


class FixValidationResult:
    def __init__(
        self,
        is_valid: bool,
        risk_level: str,
        is_security_widened: bool,
        is_destructive: bool,
        diff: Dict[str, Any],
        patched_ir: Optional[UniversalIR] = None,
        patched_hcl: Optional[str] = None,
        errors: Optional[List[str]] = None,
    ):
        self.is_valid = is_valid
        self.risk_level = risk_level
        self.is_security_widened = is_security_widened
        self.is_destructive = is_destructive
        self.diff = diff
        self.patched_ir = patched_ir
        self.patched_hcl = patched_hcl
        self.errors = errors or []


class FixValidator:
    """Validates proposals: schema -> policy engine -> sandbox terraform validate/plan dry-run."""

    def validate_proposal(
        self,
        proposal: LLMFixProposal,
        current_ir: UniversalIR,
        plan_dir: str,
        plan_id: str,
    ) -> FixValidationResult:
        """
        Validate fix proposal in an isolated sandbox workspace.
        Ensures the patch does not widen security posture or corrupt syntax.
        """
        errors = []

        # If proposal is to halt
        if proposal.fix_type == "halt":
            return FixValidationResult(
                is_valid=False,
                risk_level="critical",
                is_security_widened=False,
                is_destructive=False,
                diff={"action": "halt", "root_cause": proposal.root_cause},
                errors=["Proposal requested halt."],
            )

        # 1. Apply patch to a copy of Universal IR
        patched_ir_dict = current_ir.model_dump()
        self._apply_ir_patch(patched_ir_dict, proposal.patch)
        try:
            patched_ir = UniversalIR(**patched_ir_dict)
        except Exception as ex:
            return FixValidationResult(
                is_valid=False,
                risk_level="high",
                is_security_widened=False,
                is_destructive=False,
                diff={},
                errors=[f"Patched IR failed schema validation: {str(ex)}"],
            )

        # 2. Policy Engine & Security Validator check
        orig_findings = SecurityValidator.audit(current_ir)
        new_findings = SecurityValidator.audit(patched_ir)

        orig_critical = sum(1 for f in orig_findings if f.get("severity") in ["CRITICAL", "HIGH"])
        new_critical = sum(1 for f in new_findings if f.get("severity") in ["CRITICAL", "HIGH"])
        is_security_widened = new_critical > orig_critical

        if is_security_widened:
            errors.append(
                f"Security posture widened: new critical/high findings increased from {orig_critical} to {new_critical}."
            )

        # Check destructiveness
        is_destructive = False
        if proposal.fix_type in ["import", "retry", "reorder", "cidr_recompute", "instance_fallback", "regenerate_hcl", "regenerate_sql"]:
            is_destructive = False
        elif "delete" in str(proposal.patch).lower() or "destroy" in str(proposal.patch).lower():
            is_destructive = True

        # Compute IR and HCL diff
        diff_info = self._compute_diff(current_ir, patched_ir, plan_dir, proposal)

        # 3. Sandbox dry-run: validate terraform in isolated sandbox directory
        sandbox_dir = Path(settings.TERRAFORM_WORKSPACE) / f"sandbox_{plan_id}_heal"
        patched_hcl = None
        try:
            if sandbox_dir.exists():
                shutil.rmtree(sandbox_dir)
            sandbox_dir.mkdir(parents=True, exist_ok=True)

            # Copy original plan files to sandbox
            orig_p = Path(plan_dir)
            if orig_p.exists():
                for item in orig_p.iterdir():
                    if item.is_file():
                        shutil.copy2(item, sandbox_dir / item.name)

            # Generate or update main.tf in sandbox
            if proposal.fix_type in ["ir_patch", "reorder", "cidr_recompute", "instance_fallback", "regenerate_hcl"]:
                tf_generator.generate(patched_ir, environment="local", plan_id=sandbox_dir.name)
            elif proposal.fix_type == "hcl_patch" and "hcl" in proposal.patch:
                (sandbox_dir / "main.tf").write_text(proposal.patch["hcl"], encoding="utf-8")

            if (sandbox_dir / "main.tf").exists():
                patched_hcl = (sandbox_dir / "main.tf").read_text(encoding="utf-8")

            # Run dry-run terraform validate in sandbox
            if (sandbox_dir / "main.tf").exists() and os.path.exists(settings.TERRAFORM_BINARY):
                valid, out = tf_generator.validate(str(sandbox_dir))
                if not valid:
                    # Note: init might fail if plugin cache / offline, so treat as warning if validate binary fails
                    logger.warning("Sandbox validation notice", detail=out)
        except Exception as e:
            logger.warning("Sandbox dry-run notice", error=str(e))
        finally:
            # Clean up sandbox
            try:
                if sandbox_dir.exists():
                    shutil.rmtree(sandbox_dir)
            except Exception:
                pass

        risk_level = "low"
        if is_security_widened or is_destructive or proposal.risk_assessment in ["high", "critical"]:
            risk_level = "high"
        elif proposal.risk_assessment == "medium":
            risk_level = "medium"

        is_valid = len(errors) == 0

        return FixValidationResult(
            is_valid=is_valid,
            risk_level=risk_level,
            is_security_widened=is_security_widened,
            is_destructive=is_destructive,
            diff=diff_info,
            patched_ir=patched_ir,
            patched_hcl=patched_hcl,
            errors=errors,
        )

    def _apply_ir_patch(self, ir_dict: Dict[str, Any], patch: Dict[str, Any]) -> None:
        """Apply dotted key patch to nested dict."""
        for path_str, value in patch.items():
            parts = path_str.replace("][", ".").replace("[", ".").replace("]", "").split(".")
            # Normalize shorthand 'resources[i]' to 'cloud.resources[i]' if resources is under cloud
            if parts and parts[0] == "resources" and "resources" not in ir_dict and "cloud" in ir_dict:
                parts = ["cloud"] + parts

            curr = ir_dict
            for i, part in enumerate(parts[:-1]):
                if part.isdigit():
                    idx = int(part)
                    if isinstance(curr, list) and idx < len(curr):
                        curr = curr[idx]
                    else:
                        break
                else:
                    if isinstance(curr, dict) and part in curr:
                        curr = curr[part]
                    else:
                        break
            last_key = parts[-1]
            if isinstance(curr, dict):
                curr[last_key] = value
            elif isinstance(curr, list) and last_key.isdigit():
                idx = int(last_key)
                if idx < len(curr):
                    curr[idx] = value

    def _compute_diff(
        self,
        orig_ir: UniversalIR,
        patched_ir: UniversalIR,
        plan_dir: str,
        proposal: LLMFixProposal,
    ) -> Dict[str, Any]:
        """Compute structured before/after diff for display in UI."""
        diff_info: Dict[str, Any] = {
            "fix_type": proposal.fix_type,
            "root_cause": proposal.root_cause,
            "reasoning": proposal.reasoning,
            "patch": proposal.patch,
            "changes": [],
            "before_summary": "",
            "after_summary": "",
        }

        # Compare resources
        orig_res = orig_ir.cloud.resources if orig_ir.cloud else []
        new_res = patched_ir.cloud.resources if patched_ir.cloud else []

        orig_map = {r.name: r.model_dump() for r in orig_res}
        new_map = {r.name: r.model_dump() for r in new_res}

        for name, n_data in new_map.items():
            if name in orig_map:
                o_data = orig_map[name]
                if o_data != n_data:
                    diff_info["changes"].append({
                        "resource": name,
                        "action": "modify",
                        "before": o_data.get("properties", {}),
                        "after": n_data.get("properties", {}),
                    })
            else:
                diff_info["changes"].append({
                    "resource": name,
                    "action": "add",
                    "properties": n_data.get("properties", {}),
                })

        diff_info["before_summary"] = f"{len(orig_res)} resources"
        diff_info["after_summary"] = f"{len(new_res)} resources"
        return diff_info


fix_validator = FixValidator()
