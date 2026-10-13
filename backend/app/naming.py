"""Make physical AWS resource names unique per plan.

Why: generic names ("app-data-bucket", "app-queue", ...) collide.
  * S3 bucket names are global across ALL AWS accounts, so a generic name fails on the very
    first deploy ("BucketAlreadyExists").
  * SQS / SNS / DynamoDB / IAM / RDS names are unique per account (and region), so a second
    plan with the same name fails ("already exists").

Rule: if the USER typed a name (in the request or in requirements.md) we keep it exactly.
Otherwise we append a short suffix taken from the plan id, e.g. app-data-bucket-dbeed1.

Only the resource's OWN physical name property is changed. Terraform labels (resource.name)
and references from other resources (versioning, encryption, ...) are left alone, because the
AWS adapter references buckets by label, not by physical name.
"""
import re
from typing import Any, Dict, List, Optional, Tuple

import structlog

logger = structlog.get_logger(__name__)

# terraform type -> (property holding the physical name, max length, style)
_RULES: Dict[str, Tuple[str, int, str]] = {
    "aws_s3_bucket": ("bucket_name", 63, "dns"),
    "aws_db_instance": ("identifier", 63, "dns_letter"),
    "aws_sqs_queue": ("queue_name", 80, "plain"),
    "aws_sns_topic": ("topic_name", 256, "plain"),
    "aws_dynamodb_table": ("table_name", 255, "plain"),
    "aws_iam_role": ("role_name", 64, "plain"),
}

# A name that already ends in "-<6 hex>" was suffixed by us earlier (e.g. a revised plan).
_ALREADY_SUFFIXED = re.compile(r"-[0-9a-f]{6}$")


def plan_suffix(plan_id: str) -> str:
    """'plan_dbeed1f3' -> 'dbeed1'."""
    return re.sub(r"[^0-9a-f]", "", plan_id.split("_", 1)[-1].lower())[:6] or "000000"


def _stated(name: str, text: str) -> bool:
    """True if the user typed this exact name (whole token) in the request/requirements."""
    low = text.lower()
    for candidate in {name.lower(), name.lower().replace("_", "-")}:
        if candidate and re.search(r"(?<![a-z0-9_.\-])" + re.escape(candidate) + r"(?![a-z0-9_.\-])", low):
            return True
    return False


def _clean(base: str, style: str) -> str:
    if style in ("dns", "dns_letter"):
        base = re.sub(r"[^a-z0-9.\-]", "", base.lower().replace("_", "-"))
        base = re.sub(r"-{2,}", "-", base).strip("-.")
        if style == "dns_letter" and (not base or not base[0].isalpha()):
            base = "db-" + base
        return base or ("bucket" if style == "dns" else "db")
    return re.sub(r"\s+", "-", base.strip()) or "resource"


def make_names_unique(ir: Any, user_text: str, plan_id: str, mapping: Optional[Dict[str, str]] = None) -> List[Dict[str, str]]:
    """Mutates ir.cloud.resources in place. Returns a list of {type, old, new} changes."""
    cloud = getattr(ir, "cloud", None)
    resources = getattr(cloud, "resources", None) or []
    if mapping is None:
        from app.adapters.cloud.aws import AWSAdapter
        mapping = AWSAdapter.MAPPING

    suffix = plan_suffix(plan_id)
    changes: List[Dict[str, str]] = []

    for res in resources:
        tf_type = mapping.get(res.type, res.type)
        rule = _RULES.get(tf_type)
        if not rule:
            continue
        key, max_len, style = rule
        props = res.properties if isinstance(res.properties, dict) else {}

        # Same lookup order the AWS adapter uses to pick the physical name.
        current = props.get(key) or props.get("name") or res.name
        if not current or str(current).startswith(("arn:", "${", "var.", "aws_")):
            continue
        current = str(current)

        if _stated(current, user_text) or _ALREADY_SUFFIXED.search(current):
            continue

        base = _clean(current, style)
        room = max_len - len(suffix) - 1
        new = f"{base[:room].rstrip('-.')}-{suffix}"
        if new == current:
            continue

        props[key] = new
        if key == "bucket_name" and "bucket" in props:
            props["bucket"] = new
        res.properties = props
        res.status_chip = f"NAME_UNIQUE → {new}"
        changes.append({"type": tf_type, "old": current, "new": new})

    if changes:
        note = "Names made unique for AWS: " + "; ".join(f"{c['old']} → {c['new']}" for c in changes) + \
               ". Put your own name in the request to keep it exactly."
        try:
            ir.assumptions = list(ir.assumptions or []) + [note]
        except Exception:
            pass
        logger.info("Unique resource names applied", plan_id=plan_id, changes=changes)
    return changes
