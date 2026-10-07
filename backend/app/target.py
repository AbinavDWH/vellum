from dataclasses import dataclass
from typing import Optional, Any, Union
import json
import logging
from sqlalchemy.orm import Session
from app.config import settings

logger = logging.getLogger(__name__)


class ProductionConnectionRequiredError(ValueError):
    """Raised when prod target is used without an authenticated connection."""
    pass


@dataclass
class TargetResolution:
    environment: str  # "local", "prod", "staging", "dev"
    provider: str  # "aws"
    region: str  # "us-east-1"
    connection_id: Optional[str] = None
    account_id: Optional[str] = None
    aws_access_key: Optional[str] = None
    aws_secret_key: Optional[str] = None
    is_local: bool = True
    target_label: str = ""
    error: Optional[str] = None


def resolve_target(
    plan: Optional[Any] = None,
    ir: Optional[Any] = None,
    environment: Optional[str] = None,
    connection_id: Optional[str] = None,
    region: Optional[str] = None,
    cloud_provider: Optional[str] = None,
    db: Optional[Session] = None,
    strict_prod: bool = False,
    allow_missing: bool = False,
) -> TargetResolution:
    """
    Unified target resolution function across planning, execution, verification, re-run, and UI.

    Rules:
    1. Single source of truth for target environment and credentials.
    2. Uses ONLY what the user picked in the UI or the connection attached to the plan.
       No prompt guessing.
    3. Never quietly defaults to "local" if the target is missing.
    4. Blocks PROD without an active authenticated AWS connection (no host machine fallback).
    """
    target_env: Optional[str] = None
    target_region: Optional[str] = region
    target_provider: str = cloud_provider or "aws"
    target_conn_id: Optional[str] = connection_id
    conn = None
    aws_access_key: Optional[str] = None
    aws_secret_key: Optional[str] = None
    account_id: Optional[str] = None
    close_db = False

    # 1. From Plan
    if plan is not None:
        if not target_conn_id and getattr(plan, "connection_id", None):
            target_conn_id = plan.connection_id
        if getattr(plan, "ir_json", None):
            try:
                ir_data = json.loads(plan.ir_json) if isinstance(plan.ir_json, str) else plan.ir_json
                cloud_sec = ir_data.get("cloud") if isinstance(ir_data, dict) else None
                if cloud_sec and isinstance(cloud_sec, dict):
                    if not target_env and cloud_sec.get("environment"):
                        target_env = cloud_sec.get("environment")
                    if not target_region and cloud_sec.get("region"):
                        target_region = cloud_sec.get("region")
                    if cloud_sec.get("provider"):
                        target_provider = cloud_sec.get("provider")
            except Exception:
                pass
        if not target_env and getattr(plan, "environment", None):
            target_env = plan.environment

    # 2. From IR
    if ir is not None:
        try:
            if hasattr(ir, "cloud") and ir.cloud:
                c = ir.cloud
                if not target_env and getattr(c, "environment", None):
                    target_env = c.environment
                if not target_region and getattr(c, "region", None):
                    target_region = c.region
                if getattr(c, "provider", None):
                    target_provider = c.provider
            elif isinstance(ir, dict) and ir.get("cloud"):
                c = ir["cloud"]
                if not target_env and c.get("environment"):
                    target_env = c.get("environment")
                if not target_region and c.get("region"):
                    target_region = c.get("region")
                if c.get("provider"):
                    target_provider = c.get("provider")
        except Exception:
            pass

    # 3. Explicit environment (passed from UI or request) takes precedence over implicit IR values
    if environment is not None and str(environment).strip():
        target_env = str(environment).strip()

    # 4. Resolve connection from DB if target_conn_id or target_env is available
    if db is None:
        try:
            from app.database import SessionLocal
            db = SessionLocal()
            close_db = True
        except Exception:
            pass

    try:
        if db is not None:
            from app.models import ConnectionRecord
            from app.credentials.manager import credential_manager

            if target_conn_id:
                conn = (
                    db.query(ConnectionRecord)
                    .filter(ConnectionRecord.id == target_conn_id, ConnectionRecord.is_deleted == False)
                    .first()
                )

            # If user picked a non-local env without explicit conn_id, find active connection for it
            if not conn and target_env and target_env.lower() in ["prod", "production", "staging", "stage", "dev", "development"]:
                norm_env = "prod" if target_env.lower() in ["prod", "production"] else target_env.lower()
                conn = (
                    db.query(ConnectionRecord)
                    .filter(
                        ConnectionRecord.environment == norm_env,
                        ConnectionRecord.is_deleted == False,
                        ConnectionRecord.status.in_(["connected", "active"]),
                    )
                    .order_by(ConnectionRecord.updated_at.desc())
                    .first()
                )
                if not conn:
                    conn = (
                        db.query(ConnectionRecord)
                        .filter(ConnectionRecord.environment == norm_env, ConnectionRecord.is_deleted == False)
                        .order_by(ConnectionRecord.updated_at.desc())
                        .first()
                    )

            if conn:
                target_conn_id = conn.id
                target_env = conn.environment or target_env
                target_region = target_region or conn.region or "us-east-1"
                target_provider = conn.provider or target_provider
                account_id = conn.account_id
                if conn.encrypted_access_key and conn.encrypted_secret_key:
                    try:
                        aws_access_key = credential_manager.decrypt(conn.encrypted_access_key)
                        aws_secret_key = credential_manager.decrypt(conn.encrypted_secret_key)
                    except Exception as e:
                        logger.warning("Failed to decrypt credentials for connection %s: %s", conn.id, e)
    finally:
        if close_db and db is not None:
            db.close()

    # 5. Check if target_env is missing
    if not target_env or not str(target_env).strip():
        if allow_missing:
            return TargetResolution(
                environment="",
                provider=target_provider,
                region=target_region or "us-east-1",
                is_local=False,
                error="Target environment is missing. Please select a target environment (e.g. LocalStack or an AWS connection).",
            )
        raise ValueError(
            "Target environment is missing. Please select an environment (e.g., LocalStack or an AWS connection) before proceeding."
        )

    # Normalize environment
    target_env = target_env.strip().lower()
    if target_env in ["prod", "production"]:
        target_env = "prod"
    elif target_env in ["stage", "staging"]:
        target_env = "staging"
    elif target_env in ["dev", "development"]:
        target_env = "dev"

    is_local = (target_env == "local")
    target_region = target_region or (settings.LOCALSTACK_REGION if is_local else "us-east-1") or "us-east-1"

    # 6. Block PROD without an authenticated connection
    prod_error: Optional[str] = None
    if target_env in ["prod", "staging"]:
        if not conn or not (aws_access_key and aws_secret_key):
            prod_error = (
                f"Production deployment is blocked without an active, authenticated AWS connection for {target_env.upper()}. "
                "Host computer AWS credentials fallback is prohibited to prevent accidental deployment to the wrong account."
            )
            if strict_prod:
                raise ProductionConnectionRequiredError(prod_error)

    # 7. Generate authoritative target label
    if is_local:
        account_id = account_id or "000000000000"
        target_label = f"LocalStack (Simulation) • Account: {account_id} • Region: {target_region}"
    else:
        target_label = f"AWS Cloud ({target_env.upper()}) • Account: {account_id or 'unknown'} • Region: {target_region}"

    return TargetResolution(
        environment=target_env,
        provider=target_provider,
        region=target_region,
        connection_id=target_conn_id,
        account_id=account_id,
        aws_access_key=aws_access_key,
        aws_secret_key=aws_secret_key,
        is_local=is_local,
        target_label=target_label,
        error=prod_error,
    )
