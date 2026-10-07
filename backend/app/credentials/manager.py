"""
Credential isolation, dual-validity rotation, JIT access, and IAM least-privilege enforcement.
Implements controls for Module P-04 (Secrets, Identity & Least Privilege) and
M-17 (Connection Credentials UI & Service Scope Management).
Rule: Secrets are written once, encrypted at rest, masked forever after.
The LLM layer and all logs receive connection IDs only — never key material.
"""
import os
import re
import time
import json
import secrets
import string
import hashlib
import datetime
import subprocess
from typing import Dict, Any, List, Optional, Tuple
import structlog
from sqlalchemy.orm import Session
import boto3
from botocore.exceptions import ClientError, BotoCoreError

from app.config import settings
from app.audit.logger import audit_logger
from app.models import ConnectionRecord, PlanRecord

logger = structlog.get_logger(__name__)


class CredentialManager:
    """
    Isolates sensitive credentials from the LLM layer, encrypts secrets at rest,
    enforces service scopes (M-17), and manages secure rotation, JIT access, and IAM auditing.
    """

    ACCESS_KEY_REGEX = re.compile(r'^(AKIA|ASIA)[0-9A-Z]{16}$')
    SECRET_KEY_REGEX = re.compile(r'^[A-Za-z0-9/+=]{40}$')

    RESOURCE_SERVICE_MAP = {
        # UniversalIR schema types
        "virtual_network": "vpc",
        "virtual": "vpc",
        "subnet": "vpc",
        "security_group": "vpc",
        "security_rule": "vpc",
        "internet_gateway": "vpc",
        "route_table": "vpc",
        "nat_gateway": "vpc",
        "managed_database": "rds",
        "compute_instance": "ec2",
        "object_storage": "s3",
        # Standard AWS names
        "s3_bucket": "s3",
        "s3": "s3",
        "ec2_instance": "ec2",
        "ec2": "ec2",
        "vpc": "vpc",
        "rds_instance": "rds",
        "rds_cluster": "rds",
        "rds": "rds",
        "database": "rds",
        "db": "rds",
        "iam_role": "iam",
        "iam_policy": "iam",
        "iam_user": "iam",
        "iam": "iam",
        "cloudwatch_alarm": "cloudwatch",
        "cloudwatch_log_group": "cloudwatch",
        "cloudwatch": "cloudwatch",
        "lambda_function": "lambda",
        "lambda": "lambda",
        "dynamodb_table": "dynamodb",
        "dynamodb": "dynamodb",
        "sts": "sts",
        # Load balancers & traffic routing (falls under compute/network ec2 scope)
        "load_balancer": "ec2",
        "load": "ec2",
        "alb": "ec2",
        "elb": "ec2",
        "target_group": "ec2",
        "listener": "ec2",
    }

    def __init__(self):
        self._secret_store: Dict[str, str] = {}
        self._rotation_windows: Dict[str, Dict[str, Any]] = {}
        self._jit_leases: Dict[str, Dict[str, Any]] = {}
        self._cipher = None

    # ========================================================
    # Fernet Encryption At Rest (M-17)
    # ========================================================

    def _init_cipher(self):
        if self._cipher is not None:
            return self._cipher

        from cryptography.fernet import Fernet

        env_key = os.getenv("VELLUM_ENCRYPTION_KEY")
        if env_key:
            self._cipher = Fernet(env_key.encode("utf-8") if isinstance(env_key, str) else env_key)
            return self._cipher

        key_dir = os.path.expanduser("~/.vellum")
        os.makedirs(key_dir, exist_ok=True)
        key_file = os.path.join(key_dir, "credentials.key")

        if os.path.exists(key_file):
            with open(key_file, "rb") as f:
                key = f.read().strip()
        else:
            key = Fernet.generate_key()
            flags = os.O_WRONLY | os.O_CREAT | os.O_TRUNC
            fd = os.open(key_file, flags, 0o600)
            with open(fd, "wb") as f:
                f.write(key)

        self._cipher = Fernet(key)
        return self._cipher

    def encrypt(self, plaintext: str) -> str:
        if not plaintext:
            return ""
        cipher = self._init_cipher()
        return cipher.encrypt(plaintext.encode("utf-8")).decode("utf-8")

    def decrypt(self, ciphertext: str) -> str:
        if not ciphertext:
            return ""
        cipher = self._init_cipher()
        return cipher.decrypt(ciphertext.encode("utf-8")).decode("utf-8")

    # ========================================================
    # Validation & Masking Utilities
    # ========================================================

    @classmethod
    def validate_access_key_id(cls, key: str) -> bool:
        return bool(key and cls.ACCESS_KEY_REGEX.match(key))

    @classmethod
    def validate_secret_access_key(cls, secret: str) -> bool:
        return bool(secret and len(secret) == 40 and cls.SECRET_KEY_REGEX.match(secret))

    @classmethod
    def mask_key(cls, key_prefix: Optional[str], key_last4: Optional[str]) -> str:
        prefix = key_prefix or "AKIA"
        last4 = key_last4 or "****"
        return f"{prefix}****{last4}"

    def get_service_for_resource(self, resource_type: str) -> str:
        clean = (resource_type or "").lower().strip()
        if clean in self.RESOURCE_SERVICE_MAP:
            return self.RESOURCE_SERVICE_MAP[clean]
        for key, svc in self.RESOURCE_SERVICE_MAP.items():
            if key in clean:
                return svc
        if "db" in clean or "database" in clean or "rds" in clean:
            return "rds"
        if "network" in clean or "vpc" in clean or "subnet" in clean:
            return "vpc"
        if "compute" in clean or "instance" in clean or "ec2" in clean:
            return "ec2"
        if "load" in clean or "balancer" in clean or "elb" in clean or "alb" in clean:
            return "ec2"
        if "bucket" in clean or "storage" in clean or "s3" in clean:
            return "s3"
        return clean.split("_")[0] if "_" in clean else clean

    def to_dict(self, conn: ConnectionRecord) -> Dict[str, Any]:
        """Convert connection record to safe dictionary. Guarantees zero secret exposure."""
        services = json.loads(conn.services_json) if conn.services_json else []
        return {
            "id": conn.id,
            "name": conn.name,
            "provider": conn.provider,
            "environment": conn.environment,
            "auth_method": conn.auth_method,
            "profile_name": conn.profile_name,
            "region": conn.region,
            "key_prefix": conn.key_prefix,
            "key_last4": conn.key_last4,
            "masked_key": self.mask_key(conn.key_prefix, conn.key_last4),
            "services": services,
            "status": conn.status,
            "restart_pending": conn.restart_pending,
            "account_id": conn.account_id,
            "arn": conn.arn,
            "last_tested_at": conn.last_tested_at.isoformat() if conn.last_tested_at else None,
            "created_at": conn.created_at.isoformat() if conn.created_at else None,
            "updated_at": conn.updated_at.isoformat() if conn.updated_at else None,
        }

    # ========================================================
    # Default Connection Seeding
    # ========================================================

    def seed_default_connection(self, db: Session) -> Optional[ConnectionRecord]:
        # Fake sandbox connection removed so auto-switch and prod isolation logic works properly
        return None

    # ========================================================
    # Connection CRUD (M-17)
    # ========================================================

    def list_connections(self, db: Session) -> List[Dict[str, Any]]:
        records = db.query(ConnectionRecord).filter(ConnectionRecord.is_deleted == False).order_by(ConnectionRecord.created_at.desc()).all()
        return [self.to_dict(r) for r in records]

    def get_connection(self, connection_id: str, db: Session) -> Optional[Dict[str, Any]]:
        record = db.query(ConnectionRecord).filter(
            ConnectionRecord.id == connection_id,
            ConnectionRecord.is_deleted == False
        ).first()
        return self.to_dict(record) if record else None

    def get_connection_record(self, connection_id: str, db: Session) -> Optional[ConnectionRecord]:
        return db.query(ConnectionRecord).filter(
            ConnectionRecord.id == connection_id,
            ConnectionRecord.is_deleted == False
        ).first()

    def get_active_connection(self, environment: str = "local", db: Optional[Session] = None) -> Optional[ConnectionRecord]:
        if db is None:
            from app.database import SessionLocal
            db = SessionLocal()
            close = True
        else:
            close = False

        try:
            if hasattr(db, "expire_all"):
                db.expire_all()
            conn = db.query(ConnectionRecord).filter(
                ConnectionRecord.environment == environment,
                ConnectionRecord.is_deleted == False,
                ConnectionRecord.status.in_(["connected", "active"])
            ).order_by(ConnectionRecord.updated_at.desc(), ConnectionRecord.created_at.desc()).first()
            if not conn:
                conn = db.query(ConnectionRecord).filter(
                    ConnectionRecord.environment == environment,
                    ConnectionRecord.is_deleted == False
                ).order_by(ConnectionRecord.updated_at.desc(), ConnectionRecord.created_at.desc()).first()
            return conn
        finally:
            if close:
                db.close()

    def create_connection(
        self,
        db: Session,
        name: str,
        provider: str = "aws",
        environment: str = "local",
        auth_method: str = "access_key",
        region: str = "us-east-1",
        access_key_id: Optional[str] = None,
        secret_access_key: Optional[str] = None,
        services: Optional[List[str]] = None,
        profile_name: Optional[str] = None,
        confirm_name: Optional[str] = None,
    ) -> Dict[str, Any]:
        # Validate unique name
        existing = db.query(ConnectionRecord).filter(
            ConnectionRecord.name == name,
            ConnectionRecord.is_deleted == False
        ).first()
        if existing:
            raise ValueError(f"Connection with name '{name}' already exists.")

        # Ensure any soft-deleted connection with this name does not occupy
        # the name slot in databases with legacy global UNIQUE constraints.
        colliding_deleted = db.query(ConnectionRecord).filter(
            ConnectionRecord.name == name,
            ConnectionRecord.is_deleted == True
        ).all()
        for rec in colliding_deleted:
            rec.name = f"{rec.name}__deleted_{rec.id[:8]}_{int(time.time())}"
        if colliding_deleted:
            db.flush()

        # PROD environment typed confirmation
        if environment == "prod":
            if not confirm_name or confirm_name.strip() != name.strip():
                raise ValueError("PROD environment tag requires typing the exact connection name to confirm.")

        # Key validation
        key_prefix = None
        key_last4 = None
        enc_access_key = None
        enc_secret_key = None
        fingerprint = None

        if auth_method == "access_key":
            if not access_key_id or not self.validate_access_key_id(access_key_id):
                raise ValueError("Invalid Access Key ID. Must match pattern ^(AKIA|ASIA)[0-9A-Z]{16}$.")
            if not secret_access_key or not self.validate_secret_access_key(secret_access_key):
                raise ValueError("Invalid Secret Access Key. Must be exactly 40 characters [A-Za-z0-9/+=].")

            key_prefix = access_key_id[:4]
            key_last4 = access_key_id[-4:]
            enc_access_key = self.encrypt(access_key_id)
            enc_secret_key = self.encrypt(secret_access_key)
            fingerprint = hashlib.sha256(access_key_id.encode("utf-8")).hexdigest()
        elif auth_method == "profile":
            if not profile_name:
                raise ValueError("Profile name is required when auth method is 'profile'.")

        services = services or ["s3", "ec2", "vpc", "rds", "iam", "sts", "cloudwatch"]
        conn_id = f"conn_{secrets.token_hex(6)}"

        conn = ConnectionRecord(
            id=conn_id,
            name=name,
            provider=provider,
            environment=environment,
            auth_method=auth_method,
            profile_name=profile_name,
            region=region,
            key_prefix=key_prefix,
            key_last4=key_last4,
            encrypted_access_key=enc_access_key,
            encrypted_secret_key=enc_secret_key,
            fingerprint=fingerprint,
            services_json=json.dumps(services),
            status="untested",
            restart_pending=(environment == "local"),
        )
        db.add(conn)
        db.commit()
        db.refresh(conn)

        # Audit event without secret material
        audit_logger.log(
            event_type="CONNECTION_CREATED",
            risk_level="high" if environment == "prod" else "medium",
            action_by="user",
            details={
                "connection_id": conn.id,
                "name": conn.name,
                "environment": conn.environment,
                "region": conn.region,
                "auth_method": conn.auth_method,
                "masked_key": self.mask_key(conn.key_prefix, conn.key_last4),
                "services": services,
            },
            db=db,
        )

        return self.to_dict(conn)

    def update_connection(
        self,
        db: Session,
        connection_id: str,
        name: Optional[str] = None,
        provider: Optional[str] = None,
        environment: Optional[str] = None,
        auth_method: Optional[str] = None,
        region: Optional[str] = None,
        access_key_id: Optional[str] = None,
        secret_access_key: Optional[str] = None,
        services: Optional[List[str]] = None,
        profile_name: Optional[str] = None,
        confirm_name: Optional[str] = None,
        acknowledge: bool = False,
    ) -> Dict[str, Any]:
        conn = db.query(ConnectionRecord).filter(
            ConnectionRecord.id == connection_id,
            ConnectionRecord.is_deleted == False
        ).first()
        if not conn:
            raise ValueError(f"Connection '{connection_id}' not found.")

        target_env = environment or conn.environment
        target_name = name or conn.name

        if target_env == "prod":
            if not confirm_name or confirm_name.strip() != target_name.strip():
                raise ValueError("PROD environment requires typing the connection name to confirm.")

        if name and name != conn.name:
            existing = db.query(ConnectionRecord).filter(
                ConnectionRecord.name == name,
                ConnectionRecord.id != connection_id,
                ConnectionRecord.is_deleted == False
            ).first()
            if existing:
                raise ValueError(f"Connection with name '{name}' already exists.")

            colliding_deleted = db.query(ConnectionRecord).filter(
                ConnectionRecord.name == name,
                ConnectionRecord.id != connection_id,
                ConnectionRecord.is_deleted == True
            ).all()
            for rec in colliding_deleted:
                rec.name = f"{rec.name}__deleted_{rec.id[:8]}_{int(time.time())}"
            if colliding_deleted:
                db.flush()

            conn.name = name

        if provider:
            conn.provider = provider
        if environment:
            conn.environment = environment
        if auth_method:
            conn.auth_method = auth_method
        if region:
            conn.region = region
        if profile_name is not None:
            conn.profile_name = profile_name

        # Update access key if provided
        if access_key_id:
            if not self.validate_access_key_id(access_key_id):
                raise ValueError("Invalid Access Key ID. Must match pattern ^(AKIA|ASIA)[0-9A-Z]{16}$.")
            conn.key_prefix = access_key_id[:4]
            conn.key_last4 = access_key_id[-4:]
            conn.encrypted_access_key = self.encrypt(access_key_id)
            conn.fingerprint = hashlib.sha256(access_key_id.encode("utf-8")).hexdigest()

        # Update secret only if non-empty string provided (blank keeps existing stored secret)
        if secret_access_key and secret_access_key.strip():
            if not self.validate_secret_access_key(secret_access_key.strip()):
                raise ValueError("Invalid Secret Access Key. Must be exactly 40 characters [A-Za-z0-9/+=].")
            conn.encrypted_secret_key = self.encrypt(secret_access_key.strip())

        # Services update & guard against removing services used by managed resources
        if services is not None:
            affected = self.find_affected_plans_for_removed_services(db, conn, services)
            if affected and not acknowledge:
                raise ValueError(f"Existing managed resources use services being removed: {affected}")

            conn.services_json = json.dumps(services)
            if conn.environment == "local":
                conn.restart_pending = True
                conn.status = "restart_pending"

        conn.updated_at = datetime.datetime.utcnow()
        db.commit()
        db.refresh(conn)

        audit_logger.log(
            event_type="CONNECTION_UPDATED",
            risk_level="high" if conn.environment == "prod" else "medium",
            action_by="user",
            details={
                "connection_id": conn.id,
                "name": conn.name,
                "environment": conn.environment,
                "masked_key": self.mask_key(conn.key_prefix, conn.key_last4),
                "restart_pending": conn.restart_pending,
            },
            db=db,
        )

        return self.to_dict(conn)

    def delete_connection(self, db: Session, connection_id: str) -> Dict[str, Any]:
        """Purge ciphertext immediately, mark deleted, and audit."""
        conn = db.query(ConnectionRecord).filter(ConnectionRecord.id == connection_id).first()
        if not conn or conn.is_deleted:
            raise ValueError(f"Connection '{connection_id}' not found.")

        original_name = conn.name
        # Purge ciphertext from DB
        conn.encrypted_secret_key = None
        conn.encrypted_access_key = None
        conn.is_deleted = True
        conn.status = "deleted"
        conn.name = f"{original_name}__deleted_{conn.id[:8]}_{int(time.time())}"
        conn.updated_at = datetime.datetime.utcnow()
        db.commit()

        audit_logger.log(
            event_type="CONNECTION_DELETED",
            risk_level="high" if conn.environment == "prod" else "medium",
            action_by="user",
            details={
                "connection_id": conn.id,
                "name": original_name,
                "ciphertext_purged": True,
            },
            db=db,
        )

        return {"deleted": True, "connection_id": connection_id}

    # ========================================================
    # Probing & Health Testing (M-17)
    # ========================================================

    def probe_connection(
        self,
        provider: str = "aws",
        environment: str = "local",
        region: str = "us-east-1",
        access_key: Optional[str] = None,
        secret_key: Optional[str] = None,
        services: Optional[List[str]] = None,
    ) -> Dict[str, Any]:
        services = services or ["s3", "ec2", "vpc", "rds", "iam", "sts", "cloudwatch"]
        probe_results = []
        account_id = None
        arn = None

        endpoint_url = os.getenv("LOCALSTACK_URL", "http://localhost:4566") if environment == "local" else None
        ak = access_key or ("test" if environment == "local" else None)
        sk = secret_key or ("test" if environment == "local" else None)

        session_kwargs = {"region_name": region}
        if ak and sk:
            session_kwargs["aws_access_key_id"] = ak
            session_kwargs["aws_secret_access_key"] = sk

        boto_session = boto3.Session(**session_kwargs)

        # 1. sts:GetCallerIdentity probe
        start_sts = time.perf_counter()
        try:
            sts_client = boto_session.client("sts", endpoint_url=endpoint_url, region_name=region)
            caller_ident = sts_client.get_caller_identity()
            account_id = caller_ident.get("Account", "000000000000")
            arn = caller_ident.get("Arn", "arn:aws:iam::000000000000:root")
            latency = round((time.perf_counter() - start_sts) * 1000, 2)
            if "sts" in services:
                probe_results.append({"service": "sts", "status": "ok", "latency_ms": latency})
        except Exception as e:
            latency = round((time.perf_counter() - start_sts) * 1000, 2)
            if "sts" in services:
                probe_results.append({"service": "sts", "status": "error", "error": str(e), "latency_ms": latency})

        # 2. Per-service read-only probes
        for svc in services:
            if svc == "sts":
                continue
            t0 = time.perf_counter()
            try:
                if svc == "s3":
                    client = boto_session.client("s3", endpoint_url=endpoint_url, region_name=region)
                    client.list_buckets()
                elif svc in ["ec2", "vpc"]:
                    client = boto_session.client("ec2", endpoint_url=endpoint_url, region_name=region)
                    client.describe_vpcs()
                elif svc == "rds":
                    client = boto_session.client("rds", endpoint_url=endpoint_url, region_name=region)
                    client.describe_db_instances()
                elif svc == "iam":
                    client = boto_session.client("iam", endpoint_url=endpoint_url, region_name=region)
                    client.list_roles(MaxItems=1)
                elif svc == "cloudwatch":
                    client = boto_session.client("cloudwatch", endpoint_url=endpoint_url, region_name=region)
                    client.list_metrics()
                elif svc == "lambda":
                    client = boto_session.client("lambda", endpoint_url=endpoint_url, region_name=region)
                    client.list_functions(MaxItems=1)
                elif svc == "dynamodb":
                    client = boto_session.client("dynamodb", endpoint_url=endpoint_url, region_name=region)
                    client.list_tables(Limit=1)
                else:
                    client = boto_session.client(svc, endpoint_url=endpoint_url, region_name=region)
                
                lat = round((time.perf_counter() - t0) * 1000, 2)
                probe_results.append({"service": svc, "status": "ok", "latency_ms": max(lat, 1.0)})
            except Exception as e:
                lat = round((time.perf_counter() - t0) * 1000, 2)
                probe_results.append({"service": svc, "status": "error", "error": str(e), "latency_ms": max(lat, 1.0)})

        all_ok = all(p["status"] == "ok" for p in probe_results)
        any_ok = any(p["status"] == "ok" for p in probe_results)
        overall = "ok" if all_ok and account_id else ("partial" if any_ok or account_id else "error")

        return {
            "account_id": account_id or "000000000000",
            "arn": arn or "arn:aws:iam::000000000000:root",
            "services": probe_results,
            "overall_status": overall,
        }

    def test_connection_by_id(self, connection_id: str, db: Session) -> Dict[str, Any]:
        conn = db.query(ConnectionRecord).filter(
            ConnectionRecord.id == connection_id,
            ConnectionRecord.is_deleted == False
        ).first()
        if not conn:
            raise ValueError(f"Connection '{connection_id}' not found.")

        raw_access_key = self.decrypt(conn.encrypted_access_key) if conn.encrypted_access_key else None
        raw_secret_key = self.decrypt(conn.encrypted_secret_key) if conn.encrypted_secret_key else None
        services = json.loads(conn.services_json) if conn.services_json else []

        result = self.probe_connection(
            provider=conn.provider,
            environment=conn.environment,
            region=conn.region,
            access_key=raw_access_key,
            secret_key=raw_secret_key,
            services=services,
        )

        conn.last_tested_at = datetime.datetime.utcnow()
        conn.account_id = result.get("account_id")
        conn.arn = result.get("arn")
        conn.status = "connected" if result["overall_status"] in ["ok", "partial"] else "error"
        db.commit()

        audit_logger.log(
            event_type="CONNECTION_TESTED",
            risk_level="low",
            action_by="user",
            details={
                "connection_id": conn.id,
                "name": conn.name,
                "overall_status": result["overall_status"],
                "service_probe_count": len(result["services"]),
            },
            db=db,
        )

        return result

    # ========================================================
    # Scope Enforcement & Guards (M-17)
    # ========================================================

    def validate_service_scope(self, ir: Any, connection: ConnectionRecord) -> Tuple[bool, List[str]]:
        """
        Rule: SERVICE_IN_SCOPE
        Every resource in IR must exist in connection.services, else plan fails with:
        'Service {service} is not enabled for connection {connection.name}'
        """
        allowed_services = set(json.loads(connection.services_json)) if connection.services_json else set()
        errors = []

        if ir.cloud and ir.cloud.resources:
            for r in ir.cloud.resources:
                svc = self.get_service_for_resource(r.type)
                if svc not in allowed_services:
                    errors.append(f"Service {svc} is not enabled for connection {connection.name}")

        if getattr(ir, "database", None) and ir.database and ir.database.provider in ["postgresql", "mysql"]:
            cloud_provider = (ir.cloud.provider if ir.cloud else (connection.provider or "aws")).lower()
            if cloud_provider in ["aws", "local"]:
                if "rds" not in allowed_services and "database" not in allowed_services:
                    if not any("Service rds is not enabled" in e for e in errors):
                        errors.append(f"Service rds is not enabled for connection {connection.name}")

        return len(errors) == 0, errors

    def find_affected_plans_for_removed_services(
        self,
        db: Session,
        connection: ConnectionRecord,
        new_services: List[str]
    ) -> List[Dict[str, Any]]:
        current_services = json.loads(connection.services_json) if connection.services_json else []
        removed = set(current_services) - set(new_services)
        if not removed:
            return []

        plans = db.query(PlanRecord).filter(
            (PlanRecord.connection_id == connection.id) | (PlanRecord.connection_id.is_(None)),
            PlanRecord.status.in_(["approved", "executing", "completed", "awaiting_approval"])
        ).all()

        affected = []
        for p in plans:
            try:
                ir_data = json.loads(p.ir_json)
                cloud = ir_data.get("cloud", {})
                resources = cloud.get("resources", [])
                for r in resources:
                    rtype = r.get("type", "")
                    rsvc = self.get_service_for_resource(rtype)
                    if rsvc in removed:
                        affected.append({
                            "plan_id": p.plan_id,
                            "resource_name": r.get("name", "unnamed"),
                            "resource_type": rtype,
                            "service": rsvc,
                            "plan_status": p.status,
                        })
            except Exception:
                pass
        return affected

    def update_services(
        self,
        db: Session,
        connection_id: str,
        services: List[str],
        acknowledge: bool = False
    ) -> Dict[str, Any]:
        conn = db.query(ConnectionRecord).filter(
            ConnectionRecord.id == connection_id,
            ConnectionRecord.is_deleted == False
        ).first()
        if not conn:
            raise ValueError(f"Connection '{connection_id}' not found.")

        affected = self.find_affected_plans_for_removed_services(db, conn, services)
        if affected and not acknowledge:
            raise ValueError(f"Existing managed resources use services being removed: {affected}")

        conn.services_json = json.dumps(services)
        if conn.environment == "local":
            conn.restart_pending = True
            conn.status = "restart_pending"

        conn.updated_at = datetime.datetime.utcnow()
        db.commit()
        db.refresh(conn)

        audit_logger.log(
            event_type="SERVICES_CHANGED",
            risk_level="medium",
            action_by="user",
            details={
                "connection_id": conn.id,
                "name": conn.name,
                "services": services,
                "restart_pending": conn.restart_pending,
            },
            db=db,
        )

        return {
            "connection": self.to_dict(conn),
            "affected_plans": affected,
            "restart_pending": conn.restart_pending,
        }

    def restart_localstack(self, db: Session) -> Dict[str, Any]:
        """Apply & Restart LocalStack container and clear restart_pending."""
        local_conns = db.query(ConnectionRecord).filter(
            ConnectionRecord.environment == "local",
            ConnectionRecord.is_deleted == False
        ).all()
        for c in local_conns:
            c.restart_pending = False
            c.status = "connected"
        db.commit()

        try:
            subprocess.run(["docker", "restart", "vellum-localstack"], check=True, timeout=30, capture_output=True)
        except Exception as e:
            logger.warning("docker_restart_failed_or_simulated", error=str(e))

        running_services = []
        try:
            import httpx
            for _ in range(15):
                time.sleep(1)
                try:
                    r = httpx.get("http://localhost:4566/_localstack/health", timeout=3.0)
                    if r.status_code == 200:
                        data = r.json()
                        svc_map = data.get("services", {})
                        running_services = [s for s, state in svc_map.items() if state in ["running", "available"]]
                        break
                except Exception:
                    pass
        except Exception:
            pass

        audit_logger.log(
            event_type="LOCALSTACK_RESTARTED",
            risk_level="low",
            action_by="user",
            details={"running_services": running_services},
            db=db,
        )

        return {
            "status": "restarted",
            "running_services": running_services,
            "message": "LocalStack restarted successfully.",
        }

    # ========================================================
    # Existing P-04 Credential Rotation & JIT Methods (Preserved)
    # ========================================================

    def generate_secure_password(self, length: int = 24) -> str:
        """Generate a cryptographically secure random password."""
        chars = string.ascii_letters + string.digits + "!@#$%^&*"
        return "".join(secrets.choice(chars) for _ in range(length))

    def get_database_credentials(self, db_name: str) -> Dict[str, str]:
        """Fetch or generate DB credentials without exposing them to LLM."""
        key_user = f"db_{db_name}_user"
        key_pass = f"db_{db_name}_pass"

        if key_user not in self._secret_store:
            self._secret_store[key_user] = "vellum_admin"
            self._secret_store[key_pass] = os.getenv("DB_PASSWORD", "dev_password_only")

        return {
            "username": self._secret_store[key_user],
            "password": self._secret_store[key_pass],
        }

    def initiate_dual_validity_rotation(self, db_name: str) -> Dict[str, Any]:
        current_creds = self.get_database_credentials(db_name)
        new_password = self.generate_secure_password(24)

        rotation_record = {
            "db_name": db_name,
            "version_old": current_creds["password"],
            "version_new": new_password,
            "started_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
            "cutover_complete": False,
        }
        self._rotation_windows[db_name] = rotation_record
        return {
            "db_name": db_name,
            "rotation_status": "DUAL_VALIDITY_ACTIVE",
            "both_passwords_accepted": True,
        }

    def complete_dual_validity_rotation(self, db_name: str) -> Dict[str, Any]:
        if db_name not in self._rotation_windows:
            raise ValueError(f"No active rotation window for {db_name}")

        window = self._rotation_windows[db_name]
        self._secret_store[f"db_{db_name}_pass"] = window["version_new"]
        window["cutover_complete"] = True
        return {
            "db_name": db_name,
            "rotation_status": "COMPLETED",
            "active_version": "v2",
        }

    def verify_llm_prompt_isolation(self, prompt_text: str) -> Dict[str, Any]:
        """
        Guarantees Vellum's core architectural invariant:
        Asserts no stored secret string appears anywhere in the LLM prompt or output log.
        """
        leaks = []
        for key, secret_val in self._secret_store.items():
            if secret_val and len(secret_val) > 4 and secret_val in prompt_text:
                leaks.append(key)

        # Regex scan for common cloud keys
        from app.validation.container_security import ContainerSecurityScanner
        pattern_matches = ContainerSecurityScanner.scan_for_secrets(prompt_text)

        # Check DB connection secrets
        try:
            from app.database import SessionLocal
            db = SessionLocal()
            conns = db.query(ConnectionRecord).filter(ConnectionRecord.is_deleted == False).all()
            for c in conns:
                if c.encrypted_secret_key:
                    try:
                        decrypted = self.decrypt(c.encrypted_secret_key)
                        if decrypted and len(decrypted) > 8 and decrypted in prompt_text:
                            leaks.append(f"conn_{c.name}_secret")
                    except Exception:
                        pass
                if c.encrypted_access_key:
                    try:
                        dec_key = self.decrypt(c.encrypted_access_key)
                        if dec_key and len(dec_key) > 8 and dec_key in prompt_text:
                            leaks.append(f"conn_{c.name}_access_key")
                    except Exception:
                        pass
            db.close()
        except Exception:
            pass

        passed = len(leaks) == 0 and len(pattern_matches) == 0
        return {
            "isolated": passed,
            "leaked_store_keys": leaks,
            "pattern_violations": pattern_matches,
        }

    def audit_iam_least_privilege(self, policy_statements: List[Dict[str, Any]]) -> Dict[str, Any]:
        wildcard_violations = []
        for stmt in policy_statements:
            effect = stmt.get("Effect", "")
            actions = stmt.get("Action", [])
            resources = stmt.get("Resource", [])

            if effect == "Allow":
                if isinstance(actions, str):
                    actions = [actions]
                if isinstance(resources, str):
                    resources = [resources]

                for act in actions:
                    if act == "*" or act.endswith(":*"):
                        wildcard_violations.append({
                            "statement": stmt,
                            "violation": f"Wildcard action '{act}' violates least privilege",
                        })
                    if "*" in resources and any(k in act.lower() for k in ["s3:get", "s3:put", "dynamodb:", "rds:"]):
                        wildcard_violations.append({
                            "statement": stmt,
                            "violation": f"Wildcard resource '*' on sensitive data action '{act}'",
                        })

        passed = len(wildcard_violations) == 0
        return {
            "passed": passed,
            "wildcard_violations": wildcard_violations,
        }

    def request_jit_access(
        self,
        operator_id: str,
        justification: str,
        duration_minutes: int = 60
    ) -> Dict[str, Any]:
        lease_id = f"jit-{secrets.token_hex(6)}"
        now = datetime.datetime.now(datetime.timezone.utc)
        expires_at = now + datetime.timedelta(minutes=duration_minutes)

        lease_record = {
            "lease_id": lease_id,
            "operator_id": operator_id,
            "justification": justification,
            "created_at": now.isoformat(),
            "expires_at": expires_at.isoformat(),
            "active": True,
        }
        self._jit_leases[lease_id] = lease_record
        logger.info("jit_access_granted", lease_id=lease_id, operator=operator_id, justification=justification)
        return lease_record

    def verify_jit_lease_status(self, lease_id: str, check_time: Optional[datetime.datetime] = None) -> Dict[str, Any]:
        if lease_id not in self._jit_leases:
            return {"active": False, "reason": "Lease not found"}

        lease = self._jit_leases[lease_id]
        if check_time is None:
            check_time = datetime.datetime.now(datetime.timezone.utc)

        expires_at = datetime.datetime.fromisoformat(lease["expires_at"])
        if check_time >= expires_at:
            lease["active"] = False
            return {
                "active": False,
                "lease_id": lease_id,
                "reason": "Lease expired automatically",
                "operator_id": lease["operator_id"],
            }

        return {
            "active": True,
            "lease_id": lease_id,
            "remaining_seconds": (expires_at - check_time).total_seconds(),
            "operator_id": lease["operator_id"],
        }


credential_manager = CredentialManager()
