from typing import List, Optional, Dict, Any, Literal
from pydantic import BaseModel, Field
from .ir import UniversalIR, ClarificationResponse


class ChatMessage(BaseModel):
    role: str  # "user", "assistant", "system"
    content: str


class ChatRequest(BaseModel):
    prompt: str
    session_id: Optional[str] = "default"
    conversation_history: List[ChatMessage] = Field(default_factory=list)
    model: Optional[str] = None
    cloud_provider: Optional[str] = "aws"
    environment: Optional[str] = "local"
    provider: Optional[str] = None  # "hybrid", "groq", "local"


class ChatMessageHistoryItem(BaseModel):
    id: str
    sender: str
    text: str
    plan_id: Optional[str] = None
    timestamp: str
    clarification: Optional[ClarificationResponse] = None


class PlanResponse(BaseModel):
    plan_id: str
    status: str  # "draft", "awaiting_approval", "approved", "rejected", "executing", "completed", "failed"
    intent: str
    risk_level: str  # "low", "medium", "high", "critical"
    requires_confirmation_text: bool
    confirmation_phrase: Optional[str] = None
    summary_preview: str
    ir: UniversalIR
    generated_terraform: Optional[str] = None
    generated_sql: Optional[str] = None
    estimated_cost_monthly: float = 0.0
    security_checks: List[Dict[str, Any]] = Field(default_factory=list)
    connection_id: Optional[str] = None
    environment: Optional[str] = "local"
    target_label: Optional[str] = None
    account_id: Optional[str] = None
    region: Optional[str] = None
    implementation_plan: List[Dict[str, Any]] = Field(default_factory=list)
    website_url: Optional[str] = None
    created_at: str


class ChatResponse(BaseModel):
    status: Literal["clarification_needed", "plan_ready", "conversation", "error"]
    message: str
    clarification: Optional[ClarificationResponse] = None
    plan: Optional[PlanResponse] = None
    rag_citations: Optional[List[Dict[str, Any]]] = None
    requirements_md: Optional[str] = None


class ApprovalDecision(str):
    APPROVE = "approve"
    REJECT = "reject"
    MODIFY = "modify"


class ApprovalRequest(BaseModel):
    decision: Literal["approve", "reject", "modify"]
    modifications: Optional[str] = None
    confirmation_text: Optional[str] = None
    custom_terraform: Optional[str] = None
    custom_sql: Optional[str] = None


class ExecutionResult(BaseModel):
    plan_id: str
    success: bool
    status: str
    run_number: int = 1
    resources_created: int = 0
    resources_updated: int = 0
    resources_deleted: int = 0
    terraform_output: Optional[str] = None
    sql_output: Optional[str] = None
    error_message: Optional[str] = None
    execution_time_seconds: float = 0.0
    recovery_options: Optional[List[str]] = Field(default_factory=list)
    created_resources: Optional[List[str]] = Field(default_factory=list)
    wire_traces_count: int = 0
    three_leg_status: Optional[str] = "pending"
    website_url: Optional[str] = None
    resource_checklist: Optional[List[Dict[str, Any]]] = Field(default_factory=list)


class WireTraceItem(BaseModel):
    seq: int
    ts: str
    plan_id: str
    execution_id: Optional[int] = None
    connection_id: Optional[str] = None
    account: Optional[str] = None
    region: Optional[str] = None
    service: str
    operation: str
    source: str = "vellum-sdk"  # "vellum-sdk" | "terraform"
    params_masked: Dict[str, Any] = Field(default_factory=dict)
    http_status: int = 200
    error_code: Optional[str] = None
    error_message: Optional[str] = None
    request_id: Optional[str] = None
    latency_ms: float = 0.0
    cloudtrail_confirmed: Optional[bool] = None


class WireTraceExportResponse(BaseModel):
    plan_id: str
    traces_count: int
    trace_hash: str
    exported_at: str
    traces: List[WireTraceItem]


class ThreeLegVerificationReport(BaseModel):
    all_legs_agreed: bool = True
    overall_status: str = "pass"  # "pass", "failed", "orphan_detected", "incident"
    leg1_intent: Dict[str, Any] = Field(default_factory=dict)
    leg2_wire: Dict[str, Any] = Field(default_factory=dict)
    leg3_truth: Dict[str, Any] = Field(default_factory=dict)
    zombie_events_detected: bool = False
    orphan_resources_detected: bool = False
    details: Dict[str, Any] = Field(default_factory=dict)


class ExecutionPolicy(BaseModel):
    on_failure: Literal["auto_destroy", "ask", "keep"] = "ask"
    on_cost_overrun: Literal["auto_destroy", "ask", "keep"] = "auto_destroy"
    max_heal_attempts: int = 3
    protected_resources: str = "keep_and_alert"


class TerminateExecutionRequest(BaseModel):
    force: bool = False
    confirmation_phrase: Optional[str] = None


class ChatCancelRequest(BaseModel):
    session_id: str = "default"


class SupervisorEventResponse(BaseModel):
    seq: int
    timestamp: str
    plan_id: str
    execution_id: Optional[int] = None
    phase: str  # "MONITOR", "DETECT", "DECIDE", "ACT", "VERIFY", "AUDIT"
    signature: Optional[str] = None
    diagnosis: Optional[str] = None
    decision: Optional[str] = None
    confidence: float = 1.0
    reasoning: Optional[str] = None
    message: str


class VerificationResult(BaseModel):
    plan_id: str
    status: str  # "success", "drift_detected", "failed", "incident", "orphan_detected"
    drift_detected: bool = False
    resources_verified: int = 0
    expected_resources: List[str] = Field(default_factory=list)
    found_resources: List[str] = Field(default_factory=list)
    missing_resources: List[str] = Field(default_factory=list)
    details: Dict[str, Any] = Field(default_factory=dict)
    target_environment: Optional[str] = None
    audited_account_id: Optional[str] = None
    audited_region: Optional[str] = None
    audited_target_label: Optional[str] = None
    audited_at: Optional[str] = None
    error_message: Optional[str] = None
    three_leg: Optional[ThreeLegVerificationReport] = None


# ========================================================
# M-13: Session Memory & Re-execution Schemas
# ========================================================

class SessionResponse(BaseModel):
    id: str
    title: str
    status: str  # "active", "has-completed-plan", "failed"
    message_count: int = 0
    last_plan_id: Optional[str] = None
    created_at: str
    updated_at: str
    requirements_md: Optional[str] = None


class RequirementsUpdateRequest(BaseModel):
    requirements_md: str


class RequirementsResponse(BaseModel):
    session_id: str
    requirements_md: str
    file_path: Optional[str] = None
    updated_at: str


class SessionCreateRequest(BaseModel):
    title: Optional[str] = None
    cloud_provider: Optional[str] = "aws"
    environment: Optional[str] = "local"


class SessionUpdateRequest(BaseModel):
    title: str


class SessionMessageResponse(BaseModel):
    id: str
    session_id: str
    role: str  # "user", "assistant", "system"
    content: str
    plan_id: Optional[str] = None
    created_at: str
    clarification: Optional[Dict[str, Any]] = None


class ReexecuteRequest(BaseModel):
    idempotency_key: Optional[str] = None


class ReexecuteResult(BaseModel):
    plan_id: str
    status: str  # "noop", "drift_detected", "approved", "completed", "failed"
    has_changes: bool = False
    message: str
    diff: Optional[Dict[str, Any]] = None
    requires_confirmation_text: bool = False
    confirmation_phrase: Optional[str] = None
    plan: Optional[PlanResponse] = None
    execution: Optional[ExecutionResult] = None


class ExecutionItemResponse(BaseModel):
    id: int
    plan_id: str
    run_number: int = 1
    status: str
    success: bool
    resources_created: int = 0
    resources_updated: int = 0
    resources_deleted: int = 0
    terraform_output: Optional[str] = None
    sql_output: Optional[str] = None
    error_message: Optional[str] = None
    duration_seconds: float = 0.0
    healing_status: Optional[str] = "none"
    healing_attempts_count: int = 0
    started_at: Optional[str] = None
    completed_at: Optional[str] = None
    resource_checklist: Optional[List[Dict[str, Any]]] = None


# ========================================================
# M-14: Self-Healing Schemas
# ========================================================

class ErrorDetectionResponse(BaseModel):
    signature: str
    error_class: str
    message: str
    is_unfixable: bool
    remediation_class: str
    diagnosis: Optional[str] = None


class HealingAttemptResponse(BaseModel):
    id: int
    execution_id: Optional[int] = None
    plan_id: str
    attempt_number: int
    error_signature: str
    error_class: str
    error_message: Optional[str] = None
    remediation_class: str
    fix_type: str
    root_cause: Optional[str] = None
    reasoning: Optional[str] = None
    confidence: float = 1.0
    risk_assessment: str = "low"
    patch_data: Optional[Dict[str, Any]] = None
    diff: Optional[Dict[str, Any]] = None
    status: str
    is_auto_applied: bool = False
    created_at: str
    updated_at: Optional[str] = None


class RemediationKBItem(BaseModel):
    id: int
    signature: str
    error_class: str
    fix_type: str
    fix_template: Optional[Dict[str, Any]] = None
    description: Optional[str] = None
    success_count: int = 0
    failure_count: int = 0
    cross_plan_failures: int = 0
    enabled: bool = True
    is_promoted: bool = False
    circuit_broken: bool = False
    version: int = 1
    created_at: str
    updated_at: Optional[str] = None


class RemediationKBUpdateRequest(BaseModel):
    enabled: Optional[bool] = None
    description: Optional[str] = None
    fix_template: Optional[Dict[str, Any]] = None


# ========================================================
# M-17: Connection Credentials & Service Scope Schemas
# ========================================================

class ConnectionResponse(BaseModel):
    id: str
    name: str
    provider: str = "aws"
    environment: str = "local"  # "local", "staging", "prod"
    auth_method: str = "access_key"  # "access_key", "profile"
    profile_name: Optional[str] = None
    region: str = "us-east-1"
    key_prefix: Optional[str] = None
    key_last4: Optional[str] = None
    masked_key: Optional[str] = None
    services: List[str] = Field(default_factory=list)
    status: str = "untested"
    restart_pending: bool = False
    account_id: Optional[str] = None
    arn: Optional[str] = None
    last_tested_at: Optional[str] = None
    created_at: Optional[str] = None
    updated_at: Optional[str] = None


class ConnectionCreateRequest(BaseModel):
    name: str
    provider: str = "aws"
    environment: str = "local"  # "local", "staging", "prod"
    auth_method: str = "access_key"  # "access_key", "profile"
    profile_name: Optional[str] = None
    access_key_id: Optional[str] = None
    secret_access_key: Optional[str] = None
    region: str = "us-east-1"
    services: List[str] = Field(default_factory=lambda: ["s3", "ec2", "vpc", "rds", "iam", "sts", "cloudwatch"])
    confirm_name: Optional[str] = None


class ConnectionUpdateRequest(BaseModel):
    name: Optional[str] = None
    provider: Optional[str] = None
    environment: Optional[str] = None
    auth_method: Optional[str] = None
    profile_name: Optional[str] = None
    access_key_id: Optional[str] = None
    secret_access_key: Optional[str] = None
    region: Optional[str] = None
    services: Optional[List[str]] = None
    confirm_name: Optional[str] = None
    acknowledge: Optional[bool] = False


class ServiceProbeResult(BaseModel):
    service: str
    status: str  # "ok" or "error"
    latency_ms: float
    error: Optional[str] = None


class ConnectionTestResponse(BaseModel):
    account_id: str
    arn: str
    services: List[ServiceProbeResult]
    overall_status: str  # "ok", "partial", "error"


class ServicesUpdateRequest(BaseModel):
    services: List[str]
    acknowledge: bool = False


class LocalStackRestartResponse(BaseModel):
    status: str
    running_services: List[str]
    message: str


class ActiveAIRequest(BaseModel):
    provider: str  # "groq" or "local"
    model: Optional[str] = None


