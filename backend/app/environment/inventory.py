import json
import time
import uuid
import boto3
from pathlib import Path
from typing import Dict, Any, List, Optional, Tuple
from concurrent.futures import ThreadPoolExecutor, as_completed
import structlog

from app.config import settings
from app.environment.models import EnvironmentSnapshot
from app.audit.logger import audit_logger

logger = structlog.get_logger(__name__)


class EnvironmentInventoryService:
    """Read-only environment introspection and snapshot service (M-15).
    
    Guarantees:
    1. Zero mutating calls: only read-only APIs (get/list/describe/head).
    2. Parallel scanning for high performance.
    3. Cached with TTL 60s to prevent API storms.
    4. Deterministic fingerprinting of environment state.
    5. Cross-checks Vellum's own Terraform state workspaces.
    """

    CACHE_TTL_SECONDS = 60.0

    MUTATING_VERBS = (
        "create", "delete", "put", "modify", "update", "attach", "detach",
        "authorize", "revoke", "run", "terminate", "start", "stop", "reboot"
    )

    def __init__(self):
        self._cache: Dict[str, EnvironmentSnapshot] = {}
        self._call_log: List[Dict[str, Any]] = []
        self._api_call_count: int = 0

    def reset_call_metrics(self):
        """Reset call metrics (useful for testing API storm assertions)."""
        self._call_log.clear()
        self._api_call_count = 0

    def get_api_call_count(self) -> int:
        return self._api_call_count

    def get_call_log(self) -> List[Dict[str, Any]]:
        return list(self._call_log)

    def assert_zero_mutating_calls(self):
        """Asserts that no mutating API calls were ever issued by this service."""
        for entry in self._call_log:
            method = entry.get("method", "").lower()
            for verb in self.MUTATING_VERBS:
                if method.startswith(verb) or f"_{verb}" in method:
                    raise AssertionError(f"Mutating API call detected in pre-flight scan: {method}")

    def _get_boto3_client(
        self,
        service_name: str,
        region: str = "us-east-1",
        environment: str = "local",
        db: Optional[Any] = None,
    ):
        """Factory for AWS / LocalStack clients."""
        if environment == "local":
            return boto3.client(
                service_name,
                endpoint_url=settings.LOCALSTACK_URL,
                aws_access_key_id="test",
                aws_secret_access_key="test",
                region_name=region,
            )

        # Real AWS (prod / staging)
        client_kwargs: Dict[str, Any] = {"region_name": region}
        if db is not None:
            try:
                from app.models import ConnectionRecord
                from app.credentials.manager import credential_manager
                conn = (
                    db.query(ConnectionRecord)
                    .filter(
                        ConnectionRecord.environment == environment,
                        ConnectionRecord.is_deleted == False,
                        ConnectionRecord.status.in_(["connected", "active"]),
                    )
                    .order_by(ConnectionRecord.updated_at.desc())
                    .first()
                )
                if not conn:
                    conn = (
                        db.query(ConnectionRecord)
                        .filter(ConnectionRecord.environment == environment, ConnectionRecord.is_deleted == False)
                        .order_by(ConnectionRecord.updated_at.desc())
                        .first()
                    )
                if conn and conn.encrypted_access_key and conn.encrypted_secret_key:
                    client_kwargs["aws_access_key_id"] = credential_manager.decrypt(conn.encrypted_access_key)
                    client_kwargs["aws_secret_access_key"] = credential_manager.decrypt(conn.encrypted_secret_key)
            except Exception:
                pass
        return boto3.client(service_name, **client_kwargs)

    def _record_call(self, service: str, method: str):
        # Safety assertion: reject any mutating call
        for verb in self.MUTATING_VERBS:
            if method.lower().startswith(verb) or f"_{verb}" in method.lower():
                raise PermissionError(f"Pre-flight scanner is strictly read-only. Mutating call '{method}' is forbidden.")

        self._api_call_count += 1
        self._call_log.append({
            "service": service,
            "method": method,
            "timestamp": time.time(),
        })

    def _scan_s3(self, region: str, environment: str = "local", db: Optional[Any] = None) -> List[str]:
        self._record_call("s3", "list_buckets")
        try:
            client = self._get_boto3_client("s3", region, environment, db)
            resp = client.list_buckets()
            return [b.get("Name", "") for b in resp.get("Buckets", []) if b.get("Name")]
        except Exception as e:
            logger.warning("Pre-flight S3 scan notice", error=str(e))
            return []

    def _scan_vpcs(self, region: str, environment: str = "local", db: Optional[Any] = None) -> List[Dict[str, Any]]:
        self._record_call("ec2", "describe_vpcs")
        try:
            client = self._get_boto3_client("ec2", region, environment, db)
            resp = client.describe_vpcs()
            results = []
            for vpc in resp.get("Vpcs", []):
                vpc_id = vpc.get("VpcId", "")
                cidr = vpc.get("CidrBlock", "")
                name_tag = ""
                for tag in vpc.get("Tags", []):
                    if tag.get("Key") == "Name":
                        name_tag = tag.get("Value", "")
                results.append({
                    "id": vpc_id,
                    "cidr_block": cidr,
                    "name": name_tag or vpc_id,
                })
            return results
        except Exception as e:
            logger.warning("Pre-flight VPC scan notice", error=str(e))
            return []

    def _scan_subnets(self, region: str, environment: str = "local", db: Optional[Any] = None) -> List[Dict[str, Any]]:
        self._record_call("ec2", "describe_subnets")
        try:
            client = self._get_boto3_client("ec2", region, environment, db)
            resp = client.describe_subnets()
            results = []
            for sub in resp.get("Subnets", []):
                results.append({
                    "id": sub.get("SubnetId", ""),
                    "vpc_id": sub.get("VpcId", ""),
                    "cidr_block": sub.get("CidrBlock", ""),
                    "az": sub.get("AvailabilityZone", ""),
                })
            return results
        except Exception as e:
            logger.warning("Pre-flight Subnet scan notice", error=str(e))
            return []

    def _scan_security_groups(self, region: str, environment: str = "local", db: Optional[Any] = None) -> List[Dict[str, Any]]:
        self._record_call("ec2", "describe_security_groups")
        try:
            client = self._get_boto3_client("ec2", region, environment, db)
            resp = client.describe_security_groups()
            results = []
            for sg in resp.get("SecurityGroups", []):
                results.append({
                    "id": sg.get("GroupId", ""),
                    "vpc_id": sg.get("VpcId", ""),
                    "name": sg.get("GroupName", ""),
                    "description": sg.get("Description", ""),
                })
            return results
        except Exception as e:
            logger.warning("Pre-flight Security Group scan notice", error=str(e))
            return []

    def _scan_rds(self, region: str, environment: str = "local", db: Optional[Any] = None) -> List[Dict[str, Any]]:
        self._record_call("rds", "describe_db_instances")
        try:
            client = self._get_boto3_client("rds", region, environment, db)
            resp = client.describe_db_instances()
            results = []
            for db_inst in resp.get("DBInstances", []):
                results.append({
                    "identifier": db_inst.get("DBInstanceIdentifier", ""),
                    "engine": db_inst.get("Engine", ""),
                    "engine_version": db_inst.get("EngineVersion", ""),
                    "instance_class": db_inst.get("DBInstanceClass", ""),
                    "status": db_inst.get("DBInstanceStatus", "available"),
                })
            return results
        except Exception as e:
            logger.warning("Pre-flight RDS scan notice", error=str(e))
            return []

    def _scan_iam(self, region: str, environment: str = "local", db: Optional[Any] = None) -> Tuple[List[str], List[str]]:
        roles = []
        users = []
        self._record_call("iam", "list_roles")
        try:
            client = self._get_boto3_client("iam", region, environment, db)
            r_resp = client.list_roles()
            roles = [r.get("RoleName", "") for r in r_resp.get("Roles", []) if r.get("RoleName")]
        except Exception as e:
            logger.warning("Pre-flight IAM roles scan notice", error=str(e))

        self._record_call("iam", "list_users")
        try:
            client = self._get_boto3_client("iam", region, environment, db)
            u_resp = client.list_users()
            users = [u.get("UserName", "") for u in u_resp.get("Users", []) if u.get("UserName")]
        except Exception as e:
            logger.warning("Pre-flight IAM users scan notice", error=str(e))

        return roles, users

    def _scan_instance_offerings(self, region: str, environment: str = "local", db: Optional[Any] = None) -> List[str]:
        self._record_call("ec2", "describe_instance_type_offerings")
        try:
            client = self._get_boto3_client("ec2", region, environment, db)
            resp = client.describe_instance_type_offerings()
            types = [t.get("InstanceType", "") for t in resp.get("InstanceTypeOfferings", []) if t.get("InstanceType")]
            if not types:
                types = ["t2.nano", "t2.micro", "t2.small", "t3.nano", "t3.micro", "t3.small", "m5.large"]
            return types
        except Exception as e:
            logger.warning("Pre-flight instance offerings notice", error=str(e))
            return ["t2.nano", "t2.micro", "t2.small", "t3.nano", "t3.micro", "t3.small"]

    def _scan_terraform_workspace_state(self) -> Dict[str, List[str]]:
        """Cross-checks Vellum's own terraform state files (terraform-workspace/*)."""
        managed: Dict[str, List[str]] = {
            "s3_bucket": [],
            "vpc": [],
            "subnet": [],
            "security_group": [],
            "rds": [],
        }

        ws_root = Path(settings.TERRAFORM_WORKSPACE)
        if not ws_root.exists():
            return managed

        for state_file in ws_root.glob("*/terraform.tfstate"):
            try:
                content = json.loads(state_file.read_text(encoding="utf-8"))
                for res in content.get("resources", []):
                    r_type = res.get("type", "")
                    instances = res.get("instances", [])
                    for inst in instances:
                        attrs = inst.get("attributes", {})
                        if r_type == "aws_s3_bucket":
                            b_name = attrs.get("bucket") or attrs.get("id")
                            if b_name and b_name not in managed["s3_bucket"]:
                                managed["s3_bucket"].append(b_name)
                        elif r_type == "aws_vpc":
                            vpc_id = attrs.get("id")
                            cidr = attrs.get("cidr_block")
                            if vpc_id and vpc_id not in managed["vpc"]:
                                managed["vpc"].append(vpc_id)
                            if cidr and cidr not in managed["vpc"]:
                                managed["vpc"].append(cidr)
                        elif r_type == "aws_subnet":
                            sub_id = attrs.get("id")
                            cidr = attrs.get("cidr_block")
                            if sub_id and sub_id not in managed["subnet"]:
                                managed["subnet"].append(sub_id)
                            if cidr and cidr not in managed["subnet"]:
                                managed["subnet"].append(cidr)
                        elif r_type == "aws_security_group":
                            sg_name = attrs.get("name")
                            if sg_name and sg_name not in managed["security_group"]:
                                managed["security_group"].append(sg_name)
                        elif r_type == "aws_db_instance":
                            db_id = attrs.get("identifier")
                            if db_id and db_id not in managed["rds"]:
                                managed["rds"].append(db_id)
            except Exception as e:
                logger.warning("Error reading terraform state file", file=str(state_file), error=str(e))

        return managed

    def get_snapshot(
        self,
        provider: str = "aws",
        region: str = "us-east-1",
        environment: str = "local",
        force_rescan: bool = False,
        plan_id: Optional[str] = None,
        db: Optional[Any] = None,
    ) -> EnvironmentSnapshot:
        """
        Retrieves or builds environment snapshot.
        If cache is younger than TTL (60s) and force_rescan is False, returns cached snapshot.
        Otherwise performs parallel read-only scan, calculates hash, and updates cache.
        """
        cache_key = f"{provider}:{environment}:{region}"
        now = time.time()

        if not force_rescan and cache_key in self._cache:
            existing = self._cache[cache_key]
            if (now - existing.timestamp) < self.CACHE_TTL_SECONDS:
                logger.debug("Returning cached environment snapshot", snapshot_id=existing.snapshot_id, age=round(now - existing.timestamp, 2))
                return existing

        # Execute parallel read-only scans
        logger.info("Executing parallel pre-flight environment scan", provider=provider, environment=environment, region=region, force_rescan=force_rescan)

        buckets = []
        vpcs = []
        subnets = []
        sgs = []
        rds_instances = []
        iam_roles = []
        iam_users = []
        offerings = []

        with ThreadPoolExecutor(max_workers=6) as executor:
            fut_s3 = executor.submit(self._scan_s3, region, environment, db)
            fut_vpcs = executor.submit(self._scan_vpcs, region, environment, db)
            fut_subnets = executor.submit(self._scan_subnets, region, environment, db)
            fut_sgs = executor.submit(self._scan_security_groups, region, environment, db)
            fut_rds = executor.submit(self._scan_rds, region, environment, db)
            fut_iam = executor.submit(self._scan_iam, region, environment, db)
            fut_offerings = executor.submit(self._scan_instance_offerings, region, environment, db)

            buckets = fut_s3.result()
            vpcs = fut_vpcs.result()
            subnets = fut_subnets.result()
            sgs = fut_sgs.result()
            rds_instances = fut_rds.result()
            iam_roles, iam_users = fut_iam.result()
            offerings = fut_offerings.result()

        # Workspace state cross-check
        managed_resources = self._scan_terraform_workspace_state()

        # Check if environment is unavailable
        is_unavailable = False
        if environment == "local":
            try:
                import httpx
                r = httpx.get(f"{settings.LOCALSTACK_URL}/_localstack/health", timeout=1.5)
                if r.status_code != 200:
                    is_unavailable = True
            except Exception:
                is_unavailable = True

        snapshot = EnvironmentSnapshot(
            snapshot_id=f"snap_{uuid.uuid4().hex[:8]}",
            provider=provider,
            region=region,
            timestamp=now,
            ttl_seconds=int(self.CACHE_TTL_SECONDS),
            unavailable=is_unavailable,
            buckets=buckets,
            vpcs=vpcs,
            subnets=subnets,
            security_groups=sgs,
            rds_instances=rds_instances,
            iam_roles=iam_roles,
            iam_users=iam_users,
            instance_offerings=offerings,
            managed_resources=managed_resources,
        )
        snapshot.snapshot_hash = snapshot.compute_hash()

        # Cache snapshot
        self._cache[cache_key] = snapshot

        # Audit log PREFLIGHT_SCAN
        try:
            audit_logger.log(
                event_type="PREFLIGHT_SCAN",
                plan_id=plan_id,
                risk_level="low",
                action_by="environment_inventory_service",
                details={
                    "snapshot_id": snapshot.snapshot_id,
                    "snapshot_hash": snapshot.snapshot_hash,
                    "provider": provider,
                    "region": region,
                    "buckets_count": len(snapshot.buckets),
                    "vpcs_count": len(snapshot.vpcs),
                    "subnets_count": len(snapshot.subnets),
                    "security_groups_count": len(snapshot.security_groups),
                    "rds_count": len(snapshot.rds_instances),
                    "iam_roles_count": len(snapshot.iam_roles),
                    "managed_resources_count": sum(len(v) for v in snapshot.managed_resources.values()),
                },
                db=db,
            )
        except Exception as e:
            logger.warning("Failed to write PREFLIGHT_SCAN audit log", error=str(e))

        return snapshot


environment_inventory = EnvironmentInventoryService()
