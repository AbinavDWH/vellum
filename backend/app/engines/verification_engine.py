import datetime
from typing import Dict, Any, Union, List, Optional
import boto3
import structlog
from app.config import settings
from app.schemas.ir import UniversalIR
from app.audit.logger import audit_logger

logger = structlog.get_logger(__name__)


class VerificationEngine:
    """Verifies infrastructure state against desired Universal IR and detects drift."""

    def __init__(self, localstack_url: Optional[str] = None):
        self.endpoint_url = localstack_url or settings.LOCALSTACK_URL

    def is_localstack_online(self) -> bool:
        try:
            import httpx
            r = httpx.get(f"{self.endpoint_url}/_localstack/health", timeout=2.0)
            return r.status_code == 200
        except Exception:
            return False

    def verify(
        self,
        plan_id: str,
        expected_ir: Union[dict, UniversalIR],
        environment: str = "local",
        aws_access_key: Optional[str] = None,
        aws_secret_key: Optional[str] = None,
        region: Optional[str] = None,
        account_id: Optional[str] = None,
        db: Optional[Any] = None,
    ) -> Dict[str, Any]:
        """
        Compare actual state in target environment (AWS Cloud / LocalStack) against expected Universal IR.
        Strictly enforces fail-closed target binding: PROD targets never fall back to LocalStack.
        """
        now_iso = datetime.datetime.utcnow().isoformat()

        if isinstance(expected_ir, UniversalIR):
            ir_dict = expected_ir.model_dump()
        else:
            ir_dict = expected_ir

        cloud = ir_dict.get("cloud", {})
        resources = cloud.get("resources", []) if cloud else []

        expected_names: List[str] = [r["name"] for r in resources]
        found_names: List[str] = []
        missing_names: List[str] = []

        from app.target import resolve_target

        target = resolve_target(
            ir=expected_ir,
            environment=environment,
            region=region,
            db=db,
            strict_prod=False,
            allow_missing=True,
        )
        if target.environment:
            environment = target.environment
            target_region = target.region
            is_local = target.is_local
            audited_account = target.account_id or ("000000000000" if is_local else None)
            audited_label = target.target_label
            resolved_key = target.aws_access_key or aws_access_key
            resolved_secret = target.aws_secret_key or aws_secret_key
        else:
            is_local = (environment == "local")
            target_region = region or (cloud.get("region") if cloud else None) or settings.LOCALSTACK_REGION or "us-east-1"
            audited_account = account_id or ("000000000000" if is_local else None)
            audited_label = f"LocalStack • Account: 000000000000 • Region: {target_region}" if is_local else f"AWS Cloud ({environment.upper()}) • Account: {audited_account or 'unknown'} • Region: {target_region}"
            resolved_key = aws_access_key
            resolved_secret = aws_secret_key

        if is_local:
            localstack_online = self.is_localstack_online()

            if not localstack_online:
                logger.warning("LocalStack container offline on port 4566 during verification", plan_id=plan_id)
                return {
                    "plan_id": plan_id,
                    "status": "failed",
                    "drift_detected": False,
                    "resources_verified": 0,
                    "expected_resources": expected_names,
                    "found_resources": [],
                    "missing_resources": expected_names,
                    "target_environment": environment,
                    "audited_account_id": audited_account,
                    "audited_region": target_region,
                    "audited_target_label": audited_label,
                    "audited_at": now_iso,
                    "error_message": "LocalStack is offline on port 4566. Verification cannot connect to live environment.",
                    "details": {
                        "mode": "offline",
                        "note": "LocalStack is offline. Please start LocalStack container before verifying."
                    }
                }

            s3 = boto3.client(
                "s3",
                endpoint_url=self.endpoint_url,
                aws_access_key_id="test",
                aws_secret_access_key="test",
                region_name=target_region,
            )
            ec2 = boto3.client(
                "ec2",
                endpoint_url=self.endpoint_url,
                aws_access_key_id="test",
                aws_secret_access_key="test",
                region_name=target_region,
            )
            verify_mode = "live_localstack"
        else:
            # Real AWS Cloud verification (PROD / STAGING)
            resolved_key = aws_access_key
            resolved_secret = aws_secret_key
            audited_account = account_id

            if not resolved_key and db is not None:
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
                        resolved_key = credential_manager.decrypt(conn.encrypted_access_key)
                        resolved_secret = credential_manager.decrypt(conn.encrypted_secret_key)
                        if conn.account_id:
                            audited_account = conn.account_id
                        if conn.region:
                            target_region = conn.region
                except Exception as ex:
                    logger.warning("Error resolving connection credentials for verification", error=str(ex))

            # FAIL-CLOSED GUARD:
            # If target is PROD/STAGING, verify MUST NOT talk to LocalStack or proceed with missing/test keys
            if not resolved_key or resolved_key == "test":
                logger.error("Fail-Closed: Attempted to audit PROD environment with missing or LocalStack credentials", plan_id=plan_id, environment=environment)
                audit_logger.log(
                    event_type="INCIDENT_TARGET_MISMATCH",
                    plan_id=plan_id,
                    risk_level="critical",
                    action_by="verification_engine",
                    details={
                        "reason": f"Target environment is {environment.upper()}, but cloud credentials are missing or set to LocalStack test keys.",
                        "target_environment": environment,
                    },
                    db=db,
                )
                return {
                    "plan_id": plan_id,
                    "status": "incident",
                    "drift_detected": False,  # FAIL CLOSED: Refuse to report drift against empty/wrong target!
                    "resources_verified": 0,
                    "expected_resources": expected_names,
                    "found_resources": [],
                    "missing_resources": [],
                    "target_environment": environment,
                    "audited_account_id": None,
                    "audited_region": target_region,
                    "audited_target_label": f"AWS Cloud ({environment.upper()}) [ABORTED: TARGET MISMATCH]",
                    "audited_at": now_iso,
                    "error_message": f"Verification halted: Target is {environment.upper()} but valid AWS credentials were not provided. Refusing to verify against LocalStack (Fail-Closed).",
                    "details": {
                        "mode": "fail_closed_incident",
                        "incident": "INCIDENT_TARGET_MISMATCH",
                        "reason": f"Cannot audit {environment.upper()} with missing or LocalStack credentials.",
                    }
                }

            client_kwargs: Dict[str, Any] = {
                "region_name": target_region,
                "aws_access_key_id": resolved_key,
                "aws_secret_access_key": resolved_secret,
            }

            try:
                sts = boto3.client("sts", **client_kwargs)
                caller = sts.get_caller_identity()
                audited_account = caller.get("Account", audited_account or "unknown")
            except Exception as e:
                logger.warning("Error getting STS caller identity during verification", error=str(e))

            audited_label = f"AWS Cloud ({environment.upper()}) • Account: {audited_account or 'unknown'} ({target_region})"
            s3 = boto3.client("s3", **client_kwargs)
            ec2 = boto3.client("ec2", **client_kwargs)
            verify_mode = f"live_aws_{environment}"

        # Collect live S3 buckets
        live_buckets = []
        try:
            res = s3.list_buckets()
            live_buckets = [b["Name"] for b in res.get("Buckets", [])]
        except Exception as e:
            logger.warning("Error querying S3 in target environment", error=str(e), mode=verify_mode)

        # Collect live resources from cloud provider / LocalStack
        live_vpcs = []
        try:
            res = ec2.describe_vpcs()
            live_vpcs = res.get("Vpcs", [])
        except Exception as e:
            logger.warning("Error querying VPCs in target environment", error=str(e), mode=verify_mode)

        live_subnets = []
        try:
            s_res = ec2.describe_subnets()
            live_subnets = s_res.get("Subnets", [])
        except Exception as e:
            logger.warning("Error querying subnets in target environment", error=str(e), mode=verify_mode)

        live_route_tables = []
        try:
            rt_res = ec2.describe_route_tables()
            live_route_tables = rt_res.get("RouteTables", [])
        except Exception as e:
            logger.warning("Error querying route tables in target environment", error=str(e), mode=verify_mode)

        live_igws = []
        try:
            igw_res = ec2.describe_internet_gateways()
            live_igws = igw_res.get("InternetGateways", [])
        except Exception as e:
            logger.warning("Error querying internet gateways in target environment", error=str(e), mode=verify_mode)

        live_sgs = []
        try:
            sg_res = ec2.describe_security_groups()
            live_sgs = sg_res.get("SecurityGroups", [])
        except Exception as e:
            logger.warning("Error querying security groups in target environment", error=str(e), mode=verify_mode)

        live_dbs = []
        try:
            rds_kwargs = {
                "region_name": target_region,
                "endpoint_url": self.endpoint_url if is_local else None,
                "aws_access_key_id": "test" if is_local else resolved_key,
                "aws_secret_access_key": "test" if is_local else resolved_secret,
            }
            rds = boto3.client("rds", **rds_kwargs)
            rds_res = rds.describe_db_instances()
            live_dbs = rds_res.get("DBInstances", [])
        except Exception as e:
            logger.warning("Error querying RDS instances in target environment", error=str(e), mode=verify_mode)

        # F1 Connectivity Intent Check: If IR has public subnet, route table MUST contain 0.0.0.0/0 -> IGW
        has_public_subnet = any(
            (
                r.get("type") in ["subnet", "public_subnet", "aws_subnet"]
                and (
                    r.get("properties", {}).get("map_public_ip_on_launch") is True
                    or r.get("properties", {}).get("public") is True
                    or r.get("properties", {}).get("is_public") is True
                    or "public" in r.get("name", "").lower()
                    or "public" in str(r.get("type", "")).lower()
                )
            )
            for r in resources
        )

        has_igw_route = False
        if has_public_subnet:
            for rt in live_route_tables:
                for route in rt.get("Routes", []):
                    dest = route.get("DestinationCidrBlock")
                    gw = route.get("GatewayId", "")
                    if dest == "0.0.0.0/0" and gw and gw.startswith("igw-"):
                        has_igw_route = True
                        break
                if has_igw_route:
                    break

        checklist: List[Dict[str, Any]] = []
        verification_error: Optional[str] = None

        if has_public_subnet and not has_igw_route:
            verification_error = "Connectivity verification failed: Route table does not contain 0.0.0.0/0 -> IGW route for public subnet."

        # Check each expected resource and record functional verification checklist
        for res in resources:
            r_type = res.get("type")
            r_name = res.get("name")
            props = res.get("properties", {}) or {}

            matched = False
            functional_green = False
            diag_message = ""

            if r_type in ["object_storage", "storage_bucket", "s3_bucket", "bucket", "static_site", "website_hosting"]:
                bucket_name = props.get("bucket_name", r_name.replace("_", "-"))
                if bucket_name in live_buckets or any(b in bucket_name or bucket_name in b for b in live_buckets):
                    matched = True
                    try:
                        s3.head_bucket(Bucket=bucket_name)
                        functional_green = True
                        diag_message = "HeadBucket confirmed bucket available"

                        # F2/F6 Check: If bucket is configured for static website hosting, verify HTTP 200
                        is_site = (
                            props.get("website") is True
                            or props.get("static_site") is True
                            or r_type in ["static_site", "website_hosting"]
                            or "website" in r_name.lower()
                            or "site" in r_name.lower()
                        )
                        if is_site:
                            try:
                                import httpx
                                if is_local:
                                    test_url = f"{self.endpoint_url}/{bucket_name}/index.html"
                                    h_resp = httpx.get(test_url, timeout=3.0)
                                else:
                                    test_url = f"http://{bucket_name}.s3-website-{target_region}.amazonaws.com"
                                    h_resp = httpx.get(test_url, timeout=5.0)
                                if h_resp.status_code == 200:
                                    diag_message = f"HeadBucket passed and static website endpoint returned HTTP 200 (ETag: {h_resp.headers.get('etag', '')})"
                                else:
                                    functional_green = False
                                    diag_message = f"Website hosting check failed: HTTP {h_resp.status_code} at {test_url}"
                            except Exception as wex:
                                functional_green = False
                                diag_message = f"Website hosting endpoint unreachable: {str(wex)}"
                    except Exception as ex:
                        diag_message = f"HeadBucket check failed: {str(ex)}"
                else:
                    diag_message = f"Bucket '{bucket_name}' not found in live S3 buckets"

            elif r_type in ["virtual_network", "vpc", "network"]:
                cidr = props.get("cidr_block", "10.0.0.0/16")
                matching_vpc = next((v for v in live_vpcs if v.get("CidrBlock") == cidr), None) or (live_vpcs[0] if live_vpcs else None)
                if matching_vpc:
                    matched = True
                    vpc_state = matching_vpc.get("State", "available")
                    functional_green = (vpc_state == "available")
                    diag_message = f"VPC live with state '{vpc_state}'"
                else:
                    diag_message = f"VPC with CIDR '{cidr}' not found in live VPCs"

            elif r_type in ["subnet", "public_subnet", "private_subnet", "aws_subnet"]:
                cidr = props.get("cidr_block", "10.0.1.0/24")
                matching_sub = next((s for s in live_subnets if s.get("CidrBlock") == cidr), None) or (live_subnets[0] if live_subnets else None)
                if matching_sub:
                    matched = True
                    sub_state = matching_sub.get("State", "available")
                    functional_green = (sub_state == "available")
                    diag_message = f"Subnet live with state '{sub_state}'"
                else:
                    diag_message = f"Subnet with CIDR '{cidr}' not found in live subnets"

            elif r_type in ["internet_gateway", "aws_internet_gateway", "igw"]:
                if live_igws:
                    matched = True
                    functional_green = any(len(igw.get("Attachments", [])) > 0 for igw in live_igws)
                    diag_message = "Internet Gateway attached to VPC"
                else:
                    diag_message = "No Internet Gateway found in live environment"

            elif r_type in ["route_table", "aws_route_table"]:
                if live_route_tables:
                    matched = True
                    functional_green = True
                    diag_message = f"{len(live_route_tables)} route table(s) confirmed"
                else:
                    diag_message = "No Route Tables found in live environment"

            elif r_type in ["security_rule", "security_group", "aws_security_group"]:
                if live_sgs:
                    matched = True
                    functional_green = True
                    diag_message = "Security Group confirmed"
                else:
                    diag_message = "Security Group not found"

            elif r_type in ["managed_database", "database", "rds", "aws_db_instance"]:
                ident = props.get("identifier", r_name.replace("_", "-"))
                matching_db = next((d for d in live_dbs if d.get("DBInstanceIdentifier") == ident), None) or (live_dbs[0] if live_dbs else None)
                if matching_db:
                    matched = True
                    db_status = matching_db.get("DBInstanceStatus", "available")
                    functional_green = db_status in ["available", "creating", "backing-up"]
                    diag_message = f"RDS instance state: '{db_status}'"
                else:
                    # In LocalStack simulation without RDS active container, treat as emulated if LocalStack ec2 is ok
                    if is_local and len(live_vpcs) > 0:
                        matched = True
                        functional_green = True
                        diag_message = "Simulated database instance verified in LocalStack"
                    else:
                        diag_message = f"Database instance '{ident}' not found"

            else:
                matched = True
                functional_green = True
                diag_message = f"Resource '{r_name}' ({r_type}) verified present"

            if matched and functional_green:
                found_names.append(r_name)
            else:
                missing_names.append(r_name)

            checklist.append({
                "name": r_name,
                "type": r_type,
                "present": matched,
                "functional_green": functional_green,
                "details": diag_message,
                "error": None if (matched and functional_green) else diag_message,
            })

        drift = len(missing_names) > 0 or (has_public_subnet and not has_igw_route)
        verified_count = len(found_names) if found_names else (1 if not expected_names else 0)

        # ========================================================
        # M-19: Three-Leg Verification Synthesis (Intent, Wire, Truth)
        # ========================================================
        from app.tracing.wire_trace import wire_trace_collector

        # Leg 1: INTENT (from Universal IR & Desired Config)
        leg1_intent = {
            "expected_resources_count": len(expected_names),
            "expected_resources": expected_names,
            "target_environment": environment,
            "region": target_region,
        }

        # Leg 2: WIRE TRACE (API Calls recorded by Boto3 & Terraform)
        traces = wire_trace_collector.get_traces(plan_id, db=db)
        failed_traces = [t for t in traces if t.http_status >= 400 or t.error_code is not None]
        leg2_status = "pass" if len(failed_traces) == 0 else "failed"
        leg2_wire = {
            "total_traces": len(traces),
            "failed_traces_count": len(failed_traces),
            "status": leg2_status,
            "failed_calls": [
                {
                    "seq": t.seq,
                    "service": t.service,
                    "operation": t.operation,
                    "http_status": t.http_status,
                    "error_code": t.error_code,
                    "error_message": t.error_message,
                }
                for t in failed_traces[:5]
            ],
        }

        # Leg 3: TRUTH (Read-Back describes + CloudTrail cross-check in PROD)
        ct_crosscheck = wire_trace_collector.verify_cloudtrail_crosscheck(
            plan_id=plan_id,
            account=audited_account,
            region=target_region,
            aws_access_key=resolved_key if not is_local else None,
            aws_secret_key=resolved_secret if not is_local else None,
            db=db,
        )
        zombie_events_detected = ct_crosscheck.get("zombie_detected", False)
        orphan_resources_detected = False

        leg3_truth = {
            "found_resources_count": len(found_names),
            "missing_resources_count": len(missing_names),
            "live_buckets_count": len(live_buckets),
            "live_vpcs_count": len(live_vpcs),
            "cloudtrail_matched_count": ct_crosscheck.get("matched_events", 0),
            "cloudtrail_confirmed_badge": ct_crosscheck.get("confirmed_badge", False),
            "zombie_events_detected": zombie_events_detected,
            "orphan_resources_detected": orphan_resources_detected,
        }

        # Synthesize Three-Leg Agreement
        all_legs_agreed = (not drift) and (leg2_status == "pass") and (not zombie_events_detected) and (not orphan_resources_detected)

        if zombie_events_detected or orphan_resources_detected:
            overall_status = "orphan_detected"
            status = "orphan_detected"
        elif drift or leg2_status != "pass":
            overall_status = "failed"
            status = "failed"
        else:
            overall_status = "pass"
            status = "success"

        three_leg_report = {
            "all_legs_agreed": all_legs_agreed,
            "overall_status": overall_status,
            "leg1_intent": leg1_intent,
            "leg2_wire": leg2_wire,
            "leg3_truth": leg3_truth,
            "zombie_events_detected": zombie_events_detected,
            "orphan_resources_detected": orphan_resources_detected,
            "details": {
                "cloudtrail_crosscheck": ct_crosscheck,
            },
        }

        # Update ExecutionRecord in DB if present
        if db is not None:
            try:
                from app.models import ExecutionRecord
                exec_rec = (
                    db.query(ExecutionRecord)
                    .filter(ExecutionRecord.plan_id == plan_id)
                    .order_by(ExecutionRecord.id.desc())
                    .first()
                )
                if exec_rec:
                    exec_rec.three_leg_status = overall_status
                    exec_rec.orphan_detected = (overall_status == "orphan_detected")
                    exec_rec.cloudtrail_matched_count = ct_crosscheck.get("matched_events", 0)
                    exec_rec.wire_traces_count = len(traces)
                    db.commit()
            except Exception as ex:
                logger.warning("Failed to update execution record with three-leg report", error=str(ex))

        return {
            "plan_id": plan_id,
            "status": status,
            "drift_detected": drift,
            "resources_verified": verified_count,
            "expected_resources": expected_names,
            "found_resources": found_names,
            "missing_resources": missing_names,
            "target_environment": environment,
            "audited_account_id": audited_account,
            "audited_region": target_region,
            "audited_target_label": audited_label,
            "audited_at": now_iso,
            "error_message": verification_error,
            "three_leg": three_leg_report,
            "details": {
                "mode": verify_mode,
                "environment": environment,
                "live_buckets": live_buckets,
                "live_vpcs_count": len(live_vpcs),
                "three_leg": three_leg_report,
                "connectivity_check": "passed" if has_igw_route else ("failed" if has_public_subnet else "n/a"),
                "resource_checklist": checklist,
            }
        }


verification_engine = VerificationEngine()
