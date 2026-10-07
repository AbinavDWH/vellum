import re
import ipaddress
import hashlib
from typing import Dict, Any, List, Optional, Tuple
import structlog

from app.schemas.ir import UniversalIR
from app.environment.models import EnvironmentSnapshot, ConflictReport
from app.environment.naming import AWSNamingValidator

logger = structlog.get_logger(__name__)


class EnvironmentConflictValidator:
    """Pre-flight Environment Introspection & Conflict Prevention Validator (M-15).
    
    Evaluates UniversalIR resources against live environment snapshot before plan generation.
    Enforces conflict resolution policies:
    - reuse | rename | ask-user | auto-recompute | auto-fallback | auto-fix | fail-fast
    """

    PROTECTED_NAMES = {
        "production-db",
        "prod-assets",
        "core-vpc",
        "master-data",
        "prod-data",
        "billing-data",
    }

    @classmethod
    def parse_user_choices_from_prompt(cls, prompt: str) -> Dict[str, str]:
        """Extracts clarification resolution decisions from prompt text."""
        choices: Dict[str, str] = {}
        # Pattern: [Clarification]: Resource '<name>' ... -> <choice>
        # Or: [Clarification]: ... -> <choice>
        lines = prompt.split("\n")
        for line in lines:
            if "[clarification]:" in line.lower():
                # Check for resource name
                res_match = re.search(r"resource\s+['\"]([^'\"]+)['\"]", line, re.IGNORECASE)
                res_name = res_match.group(1) if res_match else None

                # Extract answer after '->'
                if "->" in line:
                    choice = line.split("->")[-1].strip()
                    if res_name:
                        choices[res_name] = choice
                    choices.setdefault("_default", choice)
                elif ":" in line:
                    parts = line.split(":", 2)
                    if len(parts) >= 3:
                        choice = parts[-1].strip()
                        if res_name:
                            choices[res_name] = choice
                        choices.setdefault("_default", choice)
        return choices

    @classmethod
    def validate_and_resolve(
        cls,
        ir: UniversalIR,
        snapshot: EnvironmentSnapshot,
        user_choices: Optional[Dict[str, str]] = None,
    ) -> Tuple[List[ConflictReport], UniversalIR, bool, bool]:
        """
        Validates IR against environment snapshot and applies conflict resolution strategies.
        
        Returns:
            (conflicts, patched_ir, has_unresolved_ask_user, is_blocked)
        """
        if user_choices is None:
            user_choices = {}

        ir_dict = ir.model_dump()
        conflicts: List[ConflictReport] = []
        has_unresolved_ask_user = False
        is_blocked = False

        if not ir_dict.get("cloud") or not ir_dict["cloud"].get("resources"):
            return conflicts, ir, False, False

        resources = ir_dict["cloud"]["resources"]

        for idx, res in enumerate(resources):
            r_type = res.get("type", "").lower()
            orig_name = res.get("name", "")
            props = res.setdefault("properties", {})
            tags = res.setdefault("tags", {})
            res_id = res.get("id") or f"res_{idx}"

            # Step 1: AWS Naming Regex & Constraints (Auto-fix + notify)
            name_check = AWSNamingValidator.validate_and_fix(r_type, orig_name)
            if not name_check.is_valid:
                fixed_name = name_check.fixed_name
                conflicts.append(ConflictReport(
                    resource_id=res_id,
                    resource_type=r_type,
                    original_name=orig_name,
                    conflict_type="illegal_name",
                    strategy="auto-fix",
                    proposed_action=f"Auto-correct illegal AWS resource name to '{fixed_name}'.",
                    new_value=fixed_name,
                    status_chip=f"NAME_CORRECTED → {fixed_name}",
                    details={"reason": name_check.reason, "original": orig_name, "fixed": fixed_name},
                ))
                res["name"] = fixed_name
                tags["_status_chip"] = f"NAME_CORRECTED → {fixed_name}"
                props["_status_chip"] = f"NAME_CORRECTED → {fixed_name}"
                orig_name = fixed_name

            current_name = res["name"]

            # Step 2: Protected Names List Check (fail-fast)
            if current_name in cls.PROTECTED_NAMES:
                # Check if it exists in snapshot
                exists_in_env = (
                    current_name in snapshot.buckets
                    or any(v.get("name") == current_name for v in snapshot.vpcs)
                    or any(r.get("identifier") == current_name for r in snapshot.rds_instances)
                )
                if exists_in_env:
                    conflicts.append(ConflictReport(
                        resource_id=res_id,
                        resource_type=r_type,
                        original_name=current_name,
                        conflict_type="protected_name",
                        strategy="fail-fast",
                        proposed_action=f"Resource '{current_name}' is in the protected_names governance list and already exists. Plan blocked.",
                        status_chip="BLOCKED → protected_name",
                        details={"protected_name": current_name},
                    ))
                    tags["_status_chip"] = "BLOCKED → protected_name"
                    props["_status_chip"] = "BLOCKED → protected_name"
                    is_blocked = True
                    continue

            # Step 3: Resource Specific Introspection
            # --- A. S3 BUCKET ---
            if r_type in ["object_storage", "s3_bucket", "storage_bucket", "bucket"]:
                bucket_name = props.get("bucket_name") or props.get("bucket") or current_name.replace("_", "-")
                # Normalize bucket name
                bucket_check = AWSNamingValidator.validate_and_fix("object_storage", bucket_name)
                if not bucket_check.is_valid:
                    bucket_name = bucket_check.fixed_name
                    props["bucket_name"] = bucket_name
                    props["bucket"] = bucket_name

                # Check if managed by Vellum in local state
                is_managed_by_vellum = bucket_name in snapshot.managed_resources.get("s3_bucket", [])
                bucket_exists_externally = bucket_name in snapshot.buckets

                # Check if this bucket was already renamed from a conflicting bucket according to user_choices
                orig_renamed_from = None
                for orig_key, ch in user_choices.items():
                    if orig_key != "_default" and "rename" in ch.lower() and "to " in ch.lower():
                        t_name = ch.split("to ")[-1].strip()
                        if t_name and t_name in (bucket_name, current_name, orig_name.replace("_", "-")):
                            orig_renamed_from = orig_key
                            break

                if is_managed_by_vellum:
                    tags["_status_chip"] = "MANAGED → update in place"
                    props["_status_chip"] = "MANAGED → update in place"
                elif bucket_exists_externally:
                    # External conflict detected!
                    # Check if user made a choice
                    choice = (
                        user_choices.get(current_name)
                        or user_choices.get(bucket_name)
                        or user_choices.get("_default")
                    )

                    candidate_rename = f"{bucket_name}-{hashlib.sha256(f'{bucket_name}:{snapshot.snapshot_hash}'.encode()).hexdigest()[:4]}"

                    if choice and ("reuse" in choice.lower() or "manage" in choice.lower()):
                        # User chose REUSE
                        conflicts.append(ConflictReport(
                            resource_id=res_id,
                            resource_type=r_type,
                            original_name=bucket_name,
                            conflict_type="name_exists",
                            strategy="reuse",
                            proposed_action=f"Attach and import existing S3 bucket '{bucket_name}' into state.",
                            new_value=bucket_name,
                            status_chip="EXISTS → reuse",
                            details={"bucket_name": bucket_name, "choice": "reuse"},
                        ))
                        props["_preflight_action"] = "reuse"
                        props["_preflight_target_id"] = bucket_name
                        tags["_status_chip"] = "EXISTS → reuse"
                        props["_status_chip"] = "EXISTS → reuse"

                    elif choice and ("rename" in choice.lower()):
                        # User chose RENAME
                        target_name = candidate_rename
                        if "to " in choice.lower():
                            specified = choice.split("to ")[-1].strip()
                            if specified:
                                target_name = AWSNamingValidator.validate_and_fix("object_storage", specified).fixed_name

                        conflicts.append(ConflictReport(
                            resource_id=res_id,
                            resource_type=r_type,
                            original_name=bucket_name,
                            conflict_type="name_exists",
                            strategy="rename",
                            proposed_action=f"Rename S3 bucket to '{target_name}'.",
                            new_value=target_name,
                            status_chip=f"EXISTS → rename to {target_name}",
                            details={"before": bucket_name, "after": target_name, "choice": "rename"},
                        ))
                        res["name"] = target_name.replace("-", "_")
                        props["bucket_name"] = target_name
                        props["bucket"] = target_name
                        tags["_status_chip"] = f"EXISTS → rename to {target_name}"
                        props["_status_chip"] = f"EXISTS → rename to {target_name}"

                    elif choice and "cancel" in choice.lower():
                        conflicts.append(ConflictReport(
                            resource_id=res_id,
                            resource_type=r_type,
                            original_name=bucket_name,
                            conflict_type="name_exists",
                            strategy="fail-fast",
                            proposed_action="Plan cancelled by user due to bucket naming conflict.",
                            status_chip="CANCELLED",
                        ))
                        is_blocked = True

                    else:
                        # Default strategy: ask-user
                        has_unresolved_ask_user = True
                        conflicts.append(ConflictReport(
                            resource_id=res_id,
                            resource_type=r_type,
                            original_name=bucket_name,
                            conflict_type="name_exists",
                            strategy="ask-user",
                            proposed_action=f"Bucket '{bucket_name}' already exists in globally unique AWS namespace. User choice required.",
                            new_value=candidate_rename,
                            options=["Reuse & manage", f"Rename to {candidate_rename}", "Cancel"],
                            status_chip="EXISTS → ask-user",
                            details={"existing_bucket": bucket_name, "suggested_rename": candidate_rename},
                        ))
                        tags["_status_chip"] = "EXISTS → ask-user"
                        props["_status_chip"] = "EXISTS → ask-user"
                elif orig_renamed_from:
                    conflicts.append(ConflictReport(
                        resource_id=res_id,
                        resource_type=r_type,
                        original_name=orig_renamed_from,
                        conflict_type="name_exists",
                        strategy="rename",
                        proposed_action=f"Rename S3 bucket to '{bucket_name}'.",
                        new_value=bucket_name,
                        status_chip=f"EXISTS → rename to {bucket_name}",
                        details={"before": orig_renamed_from, "after": bucket_name, "choice": "rename"},
                    ))
                    tags["_status_chip"] = f"EXISTS → rename to {bucket_name}"
                    props["_status_chip"] = f"EXISTS → rename to {bucket_name}"
                else:
                    tags.setdefault("_status_chip", "NEW")
                    props.setdefault("_status_chip", "NEW")

            # --- B. VPC ---
            elif r_type in ["virtual_network", "vpc", "network"]:
                vpc_cidr = props.get("cidr_block", "10.0.0.0/16")
                is_managed = (
                    vpc_cidr in snapshot.managed_resources.get("vpc", [])
                    or current_name in snapshot.managed_resources.get("vpc", [])
                )
                if is_managed:
                    tags["_status_chip"] = "MANAGED → update in place"
                    props["_status_chip"] = "MANAGED → update in place"
                else:
                    # Check CIDR overlap against existing unmanaged VPCs
                    has_overlap = False
                    overlap_vpc = None
                    try:
                        net_a = ipaddress.ip_network(vpc_cidr, strict=False)
                        for existing_vpc in snapshot.vpcs:
                            ex_cidr = existing_vpc.get("cidr_block")
                            if ex_cidr:
                                net_b = ipaddress.ip_network(ex_cidr, strict=False)
                                if net_a.overlaps(net_b):
                                    has_overlap = True
                                    overlap_vpc = existing_vpc
                                    break
                    except Exception:
                        pass

                    if has_overlap and overlap_vpc:
                        choice = (
                            user_choices.get(current_name)
                            or user_choices.get(vpc_cidr)
                            or user_choices.get("_default")
                        )
                        if choice and ("reuse" in choice.lower() or "manage" in choice.lower()):
                            conflicts.append(ConflictReport(
                                resource_id=res_id,
                                resource_type=r_type,
                                original_name=current_name,
                                conflict_type="cidr_overlap",
                                strategy="reuse",
                                proposed_action=f"Attach to existing VPC {overlap_vpc.get('id')}.",
                                new_value=overlap_vpc.get("id"),
                                status_chip="EXISTS → reuse",
                            ))
                            props["_preflight_action"] = "reuse"
                            props["_preflight_target_id"] = overlap_vpc.get("id")
                            tags["_status_chip"] = "EXISTS → reuse"
                            props["_status_chip"] = "EXISTS → reuse"
                        else:
                            has_unresolved_ask_user = True
                            conflicts.append(ConflictReport(
                                resource_id=res_id,
                                resource_type=r_type,
                                original_name=current_name,
                                conflict_type="cidr_overlap",
                                strategy="ask-user",
                                proposed_action=f"VPC CIDR {vpc_cidr} overlaps with existing VPC {overlap_vpc.get('id')} ({overlap_vpc.get('cidr_block')}).",
                                options=["Reuse & manage", "Cancel"],
                                status_chip="OVERLAP → ask-user",
                            ))
                            tags["_status_chip"] = "OVERLAP → ask-user"
                            props["_status_chip"] = "OVERLAP → ask-user"
                    else:
                        tags.setdefault("_status_chip", "NEW")
                        props.setdefault("_status_chip", "NEW")

            # --- C. SUBNET (auto-recompute CIDR overlap) ---
            elif r_type == "subnet":
                subnet_cidr = props.get("cidr_block", "10.0.1.0/24")
                # Check if subnet overlaps with existing subnets in snapshot
                overlapping = False
                existing_cidrs = [s.get("cidr_block") for s in snapshot.subnets if s.get("cidr_block")]

                try:
                    cur_net = ipaddress.ip_network(subnet_cidr, strict=False)
                    for ex_cidr in existing_cidrs:
                        ex_net = ipaddress.ip_network(ex_cidr, strict=False)
                        if cur_net.overlaps(ex_net):
                            overlapping = True
                            break
                except Exception:
                    pass

                if overlapping:
                    # Strategy: auto-recompute to next non-overlapping CIDR
                    new_cidr = cls._compute_next_free_cidr(existing_cidrs, subnet_cidr)
                    conflicts.append(ConflictReport(
                        resource_id=res_id,
                        resource_type=r_type,
                        original_name=current_name,
                        conflict_type="cidr_overlap",
                        strategy="auto-recompute",
                        proposed_action=f"Subnet CIDR {subnet_cidr} overlaps with existing subnet. Auto-recomputed to {new_cidr}.",
                        new_value=new_cidr,
                        status_chip=f"OVERLAP → moved to {new_cidr}",
                        details={"before": subnet_cidr, "after": new_cidr},
                    ))
                    props["cidr_block"] = new_cidr
                    tags["_status_chip"] = f"OVERLAP → moved to {new_cidr}"
                    props["_status_chip"] = f"OVERLAP → moved to {new_cidr}"
                else:
                    tags.setdefault("_status_chip", "NEW")
                    props.setdefault("_status_chip", "NEW")

            # --- D. RDS INSTANCE ---
            elif r_type in ["managed_database", "database", "rds"]:
                db_id = props.get("identifier") or current_name.replace("_", "-")
                existing_db = next((d for d in snapshot.rds_instances if d.get("identifier") == db_id), None)

                # Check if this RDS instance was already renamed per user choice
                orig_db_renamed_from = None
                for orig_key, ch in user_choices.items():
                    if orig_key != "_default" and "rename" in ch.lower() and "to " in ch.lower():
                        t_name = ch.split("to ")[-1].strip()
                        if t_name and t_name in (db_id, current_name, orig_name.replace("_", "-")):
                            orig_db_renamed_from = orig_key
                            break

                if existing_db:
                    choice = (
                        user_choices.get(current_name)
                        or user_choices.get(db_id)
                        or user_choices.get("_default")
                    )
                    candidate_rename = f"{db_id}-{hashlib.sha256(f'{db_id}:{snapshot.snapshot_hash}'.encode()).hexdigest()[:4]}"

                    if choice and ("reuse" in choice.lower() or "manage" in choice.lower()):
                        conflicts.append(ConflictReport(
                            resource_id=res_id,
                            resource_type=r_type,
                            original_name=db_id,
                            conflict_type="name_exists",
                            strategy="reuse",
                            proposed_action=f"Attach to existing RDS instance '{db_id}'.",
                            new_value=db_id,
                            status_chip="EXISTS → reuse",
                        ))
                        props["_preflight_action"] = "reuse"
                        props["_preflight_target_id"] = db_id
                        tags["_status_chip"] = "EXISTS → reuse"
                        props["_status_chip"] = "EXISTS → reuse"
                    elif choice and "rename" in choice.lower():
                        target_name = candidate_rename
                        if "to " in choice.lower():
                            specified = choice.split("to ")[-1].strip()
                            if specified:
                                target_name = AWSNamingValidator.validate_and_fix("managed_database", specified).fixed_name
                        conflicts.append(ConflictReport(
                            resource_id=res_id,
                            resource_type=r_type,
                            original_name=db_id,
                            conflict_type="name_exists",
                            strategy="rename",
                            proposed_action=f"Rename RDS instance to '{target_name}'.",
                            new_value=target_name,
                            status_chip=f"EXISTS → rename to {target_name}",
                        ))
                        res["name"] = target_name.replace("-", "_")
                        props["identifier"] = target_name
                        tags["_status_chip"] = f"EXISTS → rename to {target_name}"
                        props["_status_chip"] = f"EXISTS → rename to {target_name}"
                    else:
                        has_unresolved_ask_user = True
                        conflicts.append(ConflictReport(
                            resource_id=res_id,
                            resource_type=r_type,
                            original_name=db_id,
                            conflict_type="name_exists",
                            strategy="ask-user",
                            proposed_action=f"RDS instance identifier '{db_id}' already exists in target environment.",
                            new_value=candidate_rename,
                            options=["Reuse & manage", f"Rename to {candidate_rename}", "Cancel"],
                            status_chip="EXISTS → ask-user",
                            details={"identifier": db_id, "suggested_rename": candidate_rename},
                        ))
                        tags["_status_chip"] = "EXISTS → ask-user"
                        props["_status_chip"] = "EXISTS → ask-user"
                elif orig_db_renamed_from:
                    conflicts.append(ConflictReport(
                        resource_id=res_id,
                        resource_type=r_type,
                        original_name=orig_db_renamed_from,
                        conflict_type="name_exists",
                        strategy="rename",
                        proposed_action=f"Rename RDS instance to '{db_id}'.",
                        new_value=db_id,
                        status_chip=f"EXISTS → rename to {db_id}",
                        details={"before": orig_db_renamed_from, "after": db_id, "choice": "rename"},
                    ))
                    tags["_status_chip"] = f"EXISTS → rename to {db_id}"
                    props["_status_chip"] = f"EXISTS → rename to {db_id}"
                else:
                    tags.setdefault("_status_chip", "NEW")
                    props.setdefault("_status_chip", "NEW")

            # --- E. SECURITY GROUP (Default strategy: reuse) ---
            elif r_type in ["security_rule", "security_group"]:
                sg_name = current_name
                matching_sg = next((s for s in snapshot.security_groups if s.get("name") == sg_name), None)
                if matching_sg:
                    conflicts.append(ConflictReport(
                        resource_id=res_id,
                        resource_type=r_type,
                        original_name=sg_name,
                        conflict_type="name_exists",
                        strategy="reuse",
                        proposed_action=f"Security group '{sg_name}' exists in target environment; attaching and reusing.",
                        new_value=matching_sg.get("id"),
                        status_chip="EXISTS → reuse",
                        details={"group_id": matching_sg.get("id"), "name": sg_name},
                    ))
                    props["_preflight_action"] = "reuse"
                    props["_preflight_target_id"] = matching_sg.get("id") or sg_name
                    tags["_status_chip"] = "EXISTS → reuse"
                    props["_status_chip"] = "EXISTS → reuse"
                else:
                    tags.setdefault("_status_chip", "NEW")
                    props.setdefault("_status_chip", "NEW")

            # --- F. IAM ROLE / USER (Default strategy: reuse) ---
            elif r_type in ["iam_role", "iam_user"]:
                name = current_name
                exists_iam = name in snapshot.iam_roles or name in snapshot.iam_users
                if exists_iam:
                    conflicts.append(ConflictReport(
                        resource_id=res_id,
                        resource_type=r_type,
                        original_name=name,
                        conflict_type="name_exists",
                        strategy="reuse",
                        proposed_action=f"IAM resource '{name}' already exists; reusing existing role/policy.",
                        new_value=name,
                        status_chip="EXISTS → reuse",
                    ))
                    props["_preflight_action"] = "reuse"
                    props["_preflight_target_id"] = name
                    tags["_status_chip"] = "EXISTS → reuse"
                    props["_status_chip"] = "EXISTS → reuse"
                else:
                    tags.setdefault("_status_chip", "NEW")
                    props.setdefault("_status_chip", "NEW")

            # --- G. EC2 INSTANCE OFFERING (Default strategy: auto-fallback) ---
            elif r_type == "compute_instance":
                inst_type = props.get("instance_type", "t3.micro")
                if snapshot.instance_offerings and inst_type not in snapshot.instance_offerings:
                    fallback = "t3.micro" if "t3.micro" in snapshot.instance_offerings else (snapshot.instance_offerings[0] if snapshot.instance_offerings else "t2.micro")
                    conflicts.append(ConflictReport(
                        resource_id=res_id,
                        resource_type=r_type,
                        original_name=current_name,
                        conflict_type="instance_unavailable",
                        strategy="auto-fallback",
                        proposed_action=f"Instance class '{inst_type}' unavailable in region/AZ. Auto-fallback to '{fallback}'.",
                        new_value=fallback,
                        status_chip=f"FALLBACK → {fallback}",
                        details={"before": inst_type, "after": fallback},
                    ))
                    props["instance_type"] = fallback
                    tags["_status_chip"] = f"FALLBACK → {fallback}"
                    props["_status_chip"] = f"FALLBACK → {fallback}"
                else:
                    tags.setdefault("_status_chip", "NEW")
                    props.setdefault("_status_chip", "NEW")

            else:
                tags.setdefault("_status_chip", "NEW")
            res["status_chip"] = tags.get("_status_chip", "NEW")

        patched_ir = UniversalIR(**ir_dict)
        return conflicts, patched_ir, has_unresolved_ask_user, is_blocked

    @classmethod
    def _compute_next_free_cidr(cls, existing_cidrs: List[str], base_cidr: str) -> str:
        """Finds next non-overlapping CIDR block (e.g. 10.0.1.0/24 -> 10.0.2.0/24 -> 10.0.3.0/24)."""
        try:
            base_net = ipaddress.ip_network(base_cidr, strict=False)
            prefixlen = base_net.prefixlen
            parent = base_net.supernet(new_prefix=16) if prefixlen > 16 else base_net

            # Find all taken networks
            taken = []
            for c in existing_cidrs:
                try:
                    taken.append(ipaddress.ip_network(c, strict=False))
                except Exception:
                    pass

            # Scan subnets inside parent
            for candidate in parent.subnets(new_prefix=prefixlen):
                if not any(candidate.overlaps(t) for t in taken):
                    return str(candidate)
        except Exception as e:
            logger.warning("Error computing next free CIDR", error=str(e))

        # Fallback heuristic
        parts = base_cidr.split(".")
        if len(parts) >= 3:
            try:
                third_octet = int(parts[2]) + 1
                return f"{parts[0]}.{parts[1]}.{third_octet}.0/24"
            except Exception:
                pass
        return "10.0.3.0/24"


environment_conflict_validator = EnvironmentConflictValidator()
