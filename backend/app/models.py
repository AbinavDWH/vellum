import datetime
import hashlib
import json
import uuid
from sqlalchemy import Column, Integer, String, Text, Boolean, Float, DateTime, ForeignKey
from sqlalchemy.orm import relationship
from app.database import Base


class PlanRecord(Base):
    __tablename__ = "plans"

    plan_id = Column(String(64), primary_key=True, index=True)
    prompt = Column(Text, nullable=False)
    intent = Column(String(64), default="create_database_and_deploy_cloud")
    risk_level = Column(String(32), default="medium")
    status = Column(String(32), default="awaiting_approval")  # draft, awaiting_approval, approved, rejected, executing, completed, failed
    confirmation_phrase = Column(String(64), nullable=True)
    requires_confirmation_text = Column(Boolean, default=False)
    
    ir_json = Column(Text, nullable=False)  # JSON serialized UniversalIR
    terraform_code = Column(Text, nullable=True)
    sql_code = Column(Text, nullable=True)
    estimated_cost_monthly = Column(Float, default=0.0)
    security_checks_json = Column(Text, default="[]")
    connection_id = Column(String(64), nullable=True, index=True)
    execution_policy_json = Column(Text, default="{}")
    
    created_at = Column(DateTime, default=datetime.datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.datetime.utcnow, onupdate=datetime.datetime.utcnow)

    approvals = relationship("ApprovalRecord", back_populates="plan", cascade="all, delete-orphan")
    executions = relationship("ExecutionRecord", back_populates="plan", cascade="all, delete-orphan", order_by="ExecutionRecord.id")
    audit_logs = relationship("AuditLogRecord", back_populates="plan", cascade="all, delete-orphan")


class ApprovalRecord(Base):
    __tablename__ = "approvals"

    id = Column(Integer, primary_key=True, autoincrement=True)
    plan_id = Column(String(64), ForeignKey("plans.plan_id"), index=True)
    decision = Column(String(32), nullable=False)  # approve, reject, modify
    confirmation_text = Column(String(255), nullable=True)
    modifications = Column(Text, nullable=True)
    reviewer = Column(String(64), default="human_operator")
    approved_at = Column(DateTime, default=datetime.datetime.utcnow)

    plan = relationship("PlanRecord", back_populates="approvals")


class ExecutionRecord(Base):
    __tablename__ = "executions"

    id = Column(Integer, primary_key=True, autoincrement=True)
    plan_id = Column(String(64), ForeignKey("plans.plan_id"), index=True)
    run_number = Column(Integer, default=1)
    status = Column(String(32), default="pending")  # running, completed, failed
    success = Column(Boolean, default=False)
    resources_created = Column(Integer, default=0)
    resources_updated = Column(Integer, default=0)
    resources_deleted = Column(Integer, default=0)
    terraform_output = Column(Text, nullable=True)
    sql_output = Column(Text, nullable=True)
    error_message = Column(Text, nullable=True)
    duration_seconds = Column(Float, default=0.0)
    started_at = Column(DateTime, default=datetime.datetime.utcnow)
    healing_status = Column(String(32), default="none")  # none, healing, healed, halted, failed
    healing_attempts_count = Column(Integer, default=0)
    wire_traces_count = Column(Integer, default=0)
    cloudtrail_matched_count = Column(Integer, default=0)
    orphan_detected = Column(Boolean, default=False)
    three_leg_status = Column(String(32), default="pending")
    created_resources_json = Column(Text, default="[]")
    resource_checklist_json = Column(Text, default="[]")

    plan = relationship("PlanRecord", back_populates="executions")
    healing_attempts = relationship("HealingAttemptRecord", back_populates="execution", cascade="all, delete-orphan", order_by="HealingAttemptRecord.attempt_number")


class HealingAttemptRecord(Base):
    """Timeline entry for a healing attempt on an execution (M-14)."""
    __tablename__ = "healing_attempts"

    id = Column(Integer, primary_key=True, autoincrement=True)
    execution_id = Column(Integer, ForeignKey("executions.id", ondelete="CASCADE"), nullable=True, index=True)
    plan_id = Column(String(64), ForeignKey("plans.plan_id"), nullable=False, index=True)
    attempt_number = Column(Integer, default=1)
    error_signature = Column(String(128), nullable=False)
    error_class = Column(String(64), nullable=False)
    error_message = Column(Text, nullable=True)
    remediation_class = Column(String(32), default="auto")  # auto, approve, halted
    fix_type = Column(String(64), default="ir_patch")  # ir_patch, hcl_patch, retry, import, reorder, cidr_recompute, instance_fallback, regenerate_hcl, regenerate_sql, halt
    root_cause = Column(Text, nullable=True)
    reasoning = Column(Text, nullable=True)
    confidence = Column(Float, default=1.0)
    risk_assessment = Column(String(32), default="low")
    patch_data = Column(Text, nullable=True)  # JSON serialized patch
    diff = Column(Text, nullable=True)  # JSON serialized before/after diff
    status = Column(String(32), default="detected")  # detected, proposed, awaiting_approval, approved, applied, rejected, halted, failed
    is_auto_applied = Column(Boolean, default=False)
    created_at = Column(DateTime, default=datetime.datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.datetime.utcnow, onupdate=datetime.datetime.utcnow)

    execution = relationship("ExecutionRecord", back_populates="healing_attempts")
    plan = relationship("PlanRecord")


class RemediationKBRecord(Base):
    """Knowledge base entry for deterministic playbooks & promoted LLM fixes (M-14)."""
    __tablename__ = "remediation_kb"

    id = Column(Integer, primary_key=True, autoincrement=True)
    signature = Column(String(128), unique=True, index=True, nullable=False)
    error_class = Column(String(64), nullable=False)
    fix_type = Column(String(64), nullable=False)
    fix_template = Column(Text, nullable=True)  # JSON string
    description = Column(Text, nullable=True)
    success_count = Column(Integer, default=0)
    failure_count = Column(Integer, default=0)
    cross_plan_failures = Column(Integer, default=0)
    enabled = Column(Boolean, default=True)
    is_promoted = Column(Boolean, default=False)
    circuit_broken = Column(Boolean, default=False)
    version = Column(Integer, default=1)
    created_at = Column(DateTime, default=datetime.datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.datetime.utcnow, onupdate=datetime.datetime.utcnow)



class AuditLogRecord(Base):
    __tablename__ = "audit_logs"

    id = Column(Integer, primary_key=True, autoincrement=True)
    plan_id = Column(String(64), ForeignKey("plans.plan_id"), nullable=True, index=True)
    event_type = Column(String(64), nullable=False)  # PLAN_GENERATED, APPROVAL_GRANTED, EXECUTION_STARTED, etc.
    risk_level = Column(String(32), default="low")
    action_by = Column(String(64), default="system")
    payload_hash = Column(String(64), nullable=True)
    details_json = Column(Text, default="{}")
    timestamp = Column(DateTime, default=datetime.datetime.utcnow)

    plan = relationship("PlanRecord", back_populates="audit_logs")

    @staticmethod
    def compute_hash(data: str) -> str:
        return hashlib.sha256(data.encode("utf-8")).hexdigest()


class SessionRecord(Base):
    """Chat session memory for multi-turn infrastructure planning (M-13)."""
    __tablename__ = "sessions"

    id = Column(String(64), primary_key=True, index=True, default=lambda: f"sess_{uuid.uuid4().hex[:12]}")
    title = Column(String(255), nullable=False)
    status = Column(String(32), default="active")  # active, has-completed-plan, failed
    message_count = Column(Integer, default=0)
    last_plan_id = Column(String(64), ForeignKey("plans.plan_id"), nullable=True)
    requirements_md = Column(Text, nullable=True)
    is_deleted = Column(Boolean, default=False)
    created_at = Column(DateTime, default=datetime.datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.datetime.utcnow, onupdate=datetime.datetime.utcnow)

    messages = relationship("MessageRecord", back_populates="session", cascade="all, delete-orphan", order_by="MessageRecord.created_at")
    last_plan = relationship("PlanRecord", foreign_keys=[last_plan_id])


class MessageRecord(Base):
    """Individual message in a persistent chat session (M-13)."""
    __tablename__ = "messages"

    id = Column(String(64), primary_key=True, index=True, default=lambda: f"msg_{uuid.uuid4().hex[:12]}")
    session_id = Column(String(64), ForeignKey("sessions.id"), index=True, nullable=False)
    role = Column(String(16), nullable=False)  # user, assistant, system
    content = Column(Text, nullable=False)
    plan_id = Column(String(64), ForeignKey("plans.plan_id"), nullable=True, index=True)
    clarification_json = Column(Text, nullable=True)
    created_at = Column(DateTime, default=datetime.datetime.utcnow)

    session = relationship("SessionRecord", back_populates="messages")
    plan = relationship("PlanRecord", foreign_keys=[plan_id])


class ChatMessageRecord(Base):
    """Legacy chat message table preserved for RAG backward-compatibility."""
    __tablename__ = "chat_messages"

    id = Column(Integer, primary_key=True, autoincrement=True)
    session_id = Column(String(64), default="default", index=True)
    sender = Column(String(16), nullable=False)  # "user" or "assistant"
    text = Column(Text, nullable=False)
    plan_id = Column(String(64), nullable=True, index=True)
    clarification_json = Column(Text, nullable=True)
    metadata_json = Column(Text, default="{}")
    created_at = Column(DateTime, default=datetime.datetime.utcnow)


class ConnectionRecord(Base):
    """Cloud provider credentials, authentication details, and services scope (M-17)."""
    __tablename__ = "connections"

    id = Column(String(64), primary_key=True, index=True, default=lambda: f"conn_{uuid.uuid4().hex[:12]}")
    name = Column(String(128), index=True, nullable=False)
    provider = Column(String(32), default="aws", nullable=False)
    environment = Column(String(32), default="local", nullable=False)  # "local", "staging", "prod"
    auth_method = Column(String(32), default="access_key", nullable=False)  # "access_key", "profile"
    profile_name = Column(String(128), nullable=True)
    region = Column(String(32), default="us-east-1", nullable=False)

    # Credential Isolation & Masking (secret material is encrypted at rest, never returned in API)
    key_prefix = Column(String(8), default="AKIA", nullable=True)
    key_last4 = Column(String(8), default="****", nullable=True)
    encrypted_access_key = Column(Text, nullable=True)
    encrypted_secret_key = Column(Text, nullable=True)
    fingerprint = Column(String(64), nullable=True)

    # Services scope (JSON array of allowed services e.g. ["s3", "ec2", ...])
    services_json = Column(Text, default='["s3", "ec2", "vpc", "rds", "iam", "sts", "cloudwatch"]')

    status = Column(String(32), default="untested")  # connected, untested, error, restart_pending
    restart_pending = Column(Boolean, default=False)
    account_id = Column(String(32), nullable=True)
    arn = Column(String(255), nullable=True)
    last_tested_at = Column(DateTime, nullable=True)

    is_deleted = Column(Boolean, default=False)
    execution_policy_json = Column(Text, default="{}")
    created_at = Column(DateTime, default=datetime.datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.datetime.utcnow, onupdate=datetime.datetime.utcnow)


class WireTraceRecordModel(Base):
    """Wire-level trace for Vellum SDK & Terraform interactions with AWS (M-19)."""
    __tablename__ = "wire_traces"

    id = Column(Integer, primary_key=True, autoincrement=True)
    plan_id = Column(String(64), ForeignKey("plans.plan_id"), nullable=False, index=True)
    execution_id = Column(Integer, nullable=True, index=True)
    seq = Column(Integer, default=1)
    timestamp = Column(DateTime, default=datetime.datetime.utcnow)
    connection_id = Column(String(64), nullable=True)
    account = Column(String(64), nullable=True)
    region = Column(String(64), nullable=True)
    service = Column(String(64), nullable=False)
    operation = Column(String(128), nullable=False)
    source = Column(String(32), default="vellum-sdk")  # vellum-sdk | terraform
    params_masked_json = Column(Text, default="{}")
    http_status = Column(Integer, default=200)
    error_code = Column(String(128), nullable=True)
    error_message = Column(Text, nullable=True)
    request_id = Column(String(128), nullable=True, index=True)
    latency_ms = Column(Float, default=0.0)
    cloudtrail_confirmed = Column(Boolean, default=None, nullable=True)


class SupervisorEventModel(Base):
    """Always-on supervisor decision stream events (M-20)."""
    __tablename__ = "supervisor_events"

    id = Column(Integer, primary_key=True, autoincrement=True)
    plan_id = Column(String(64), ForeignKey("plans.plan_id"), nullable=False, index=True)
    execution_id = Column(Integer, nullable=True, index=True)
    seq = Column(Integer, default=1)
    timestamp = Column(DateTime, default=datetime.datetime.utcnow)
    phase = Column(String(32), default="MONITOR")  # MONITOR, DETECT, DECIDE, ACT, VERIFY, AUDIT
    signature = Column(String(128), nullable=True)
    diagnosis = Column(Text, nullable=True)
    decision = Column(String(64), nullable=True)
    confidence = Column(Float, default=1.0)
    reasoning = Column(Text, nullable=True)
    message = Column(Text, nullable=False)

