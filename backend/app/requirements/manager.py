import os
from pathlib import Path
from typing import Optional
from sqlalchemy.orm import Session
import structlog

from app.config import settings
from app.models import SessionRecord

logger = structlog.get_logger(__name__)

DEFAULT_TEMPLATE = """# Architecture Specification & Requirements

## 1. System Overview & Objective
*No requirements documented yet. Converse with the Vellum AI Architect to formulate your infrastructure.*

## 2. Target Environment & Cloud Metadata
- **Cloud Provider**: {cloud_provider}
- **Environment**: {environment}
- **Target Region**: us-east-1
- **Availability Zones**: us-east-1a, us-east-1b
- **Compliance Baseline**: CIS AWS Foundations Benchmark v3.0

## 3. Network Topology & IPAM Architecture
- **VPC CIDR Block**: TBD
- **Subnet Tiering Matrix**: TBD (Public, Private Application, Private Database tiers)
- **Gateways & Egress Routing**: TBD (Internet Gateway, NAT Gateway redundancy)
- **Security Groups & Firewall Policy**: TBD (Port ingress/egress boundaries)

## 4. Compute & Workload Architecture
- **Compute Sizing**: TBD
- **Instance Profile & IAM**: TBD
- **Storage / Root Volume**: TBD (EBS gp3 KMS encrypted)

## 5. Storage Tier (Object Storage)
- **Bucket Identification**: TBD
- **Encryption at Rest**: TBD (SSE-KMS / SSE-S3)
- **Access Policies**: TBD (Public Access Block, TLS enforcement)

## 6. Managed Database Tier & Data Model
- **Database Engine**: TBD
- **Deployment Topology**: TBD (Multi-AZ / Single-AZ)
- **Storage & Backup Policy**: TBD
- **Schema & Relational Data Model**: TBD

## 7. Security, Reliability & Compliance
- **Encryption at Rest / Transit**: TBD
- **Secrets Management**: TBD (AWS Secrets Manager)
- **Monitoring & Observability**: TBD (CloudWatch Alarms)
"""


class RequirementsManager:
    """Manages persistent Markdown architecture specifications (requirements.md) per session."""

    def __init__(self, workspace_root: Optional[str] = None):
        self.workspace_root = Path(workspace_root or settings.TERRAFORM_WORKSPACE)
        self.sessions_dir = self.workspace_root / "sessions"
        self.sessions_dir.mkdir(parents=True, exist_ok=True)

    def get_session_dir(self, session_id: str) -> Path:
        clean_id = session_id or "default"
        sdir = self.sessions_dir / clean_id
        sdir.mkdir(parents=True, exist_ok=True)
        return sdir

    def get_file_path(self, session_id: str) -> Path:
        return self.get_session_dir(session_id) / "requirements.md"

    def sync_metadata(self, content: str, cloud_provider: Optional[str] = None, environment: Optional[str] = None) -> str:
        """Ensure the Markdown specification metadata matches the desired cloud provider and environment."""
        if not content:
            return content
        import re
        updated = content
        if environment:
            updated = re.sub(
                r'(\*\*Environment\*\*:\s*)[a-zA-Z0-9_-]+',
                rf'\g<1>{environment}',
                updated,
                flags=re.IGNORECASE,
            )
        if cloud_provider:
            updated = re.sub(
                r'(\*\*Cloud Provider\*\*:\s*)[a-zA-Z0-9_-]+',
                rf'\g<1>{cloud_provider.upper()}',
                updated,
                flags=re.IGNORECASE,
            )
        return updated

    def get_default_template(self, cloud_provider: str = "aws", environment: str = "local") -> str:
        return DEFAULT_TEMPLATE.format(
            cloud_provider=cloud_provider.upper(),
            environment=environment,
        )

    def get_requirements(
        self,
        session_id: str,
        cloud_provider: str = "aws",
        environment: str = "local",
        db: Optional[Session] = None,
    ) -> str:
        """Fetch the current requirements Markdown for a session."""
        # 1. Check database if session exists
        if db is not None:
            try:
                rec = db.query(SessionRecord).filter(SessionRecord.id == session_id).first()
                if rec and rec.requirements_md and rec.requirements_md.strip():
                    content = rec.requirements_md
                    if environment in ["prod", "staging"]:
                        synced = self.sync_metadata(content, cloud_provider=cloud_provider, environment=environment)
                        if synced != content:
                            content = self.save_requirements(session_id, synced, db=db)
                    # Sync to disk if missing
                    file_path = self.get_file_path(session_id)
                    if not file_path.exists():
                        try:
                            file_path.write_text(content, encoding="utf-8")
                        except Exception:
                            pass
                    return content
            except Exception as e:
                logger.warning("Error reading requirements_md from DB", session_id=session_id, error=str(e))

        # 2. Check disk
        file_path = self.get_file_path(session_id)
        if file_path.exists():
            try:
                content = file_path.read_text(encoding="utf-8").strip()
                if content:
                    if environment in ["prod", "staging"]:
                        content = self.sync_metadata(content, cloud_provider=cloud_provider, environment=environment)
                        self.save_requirements(session_id, content, db=db)
                    return content
            except Exception as e:
                logger.warning("Error reading requirements.md from disk", file=str(file_path), error=str(e))

        # 3. Fallback to default template
        initial = self.get_default_template(cloud_provider=cloud_provider, environment=environment)
        self.save_requirements(session_id, initial, db=db)
        return initial

    def save_requirements(
        self,
        session_id: str,
        content: str,
        db: Optional[Session] = None,
    ) -> str:
        """Persist requirements Markdown to both DB and disk."""
        cleaned = content.strip() if content else ""
        if not cleaned:
            cleaned = self.get_default_template()

        # 1. Save to disk
        try:
            file_path = self.get_file_path(session_id)
            file_path.write_text(cleaned, encoding="utf-8")
        except Exception as e:
            logger.error("Failed to write requirements.md to disk", session_id=session_id, error=str(e))

        # 2. Save to database
        if db is not None:
            try:
                rec = db.query(SessionRecord).filter(SessionRecord.id == session_id).first()
                if rec:
                    rec.requirements_md = cleaned
                    db.commit()
            except Exception as e:
                logger.error("Failed to save requirements_md to DB", session_id=session_id, error=str(e))
                db.rollback()

        return cleaned


requirements_manager = RequirementsManager()
