export interface ColumnDefinition {
  name: string;
  data_type: string;
  primary_key?: boolean;
  nullable?: boolean;
  unique?: boolean;
  default?: string | null;
  references?: string | null;
  description?: string | null;
}

export interface TableDefinition {
  name: string;
  description?: string | null;
  columns: ColumnDefinition[];
  indexes?: { name: string; columns: string[]; unique?: boolean }[];
  foreign_keys?: { name?: string; columns: string[]; ref_table: string; ref_columns: string[] }[];
}

export interface CollectionDefinition {
  name: string;
  document_schema: Record<string, any>;
  indexes?: (Record<string, any> | { fields: string[]; unique?: boolean })[];
  embedded_documents?: string[];
  description?: string | null;
}

export interface DatabaseSchema {
  provider: 'postgresql' | 'mysql' | 'mongodb' | string;
  database_name: string;
  name?: string;
  tables?: TableDefinition[];
  collections?: CollectionDefinition[];
  views?: any[];
  extensions?: string[];
}


export interface CloudResource {
  id?: string;
  type: string;
  name: string;
  properties: Record<string, any>;
  depends_on?: string[];
  tags?: Record<string, string>;
  status_chip?: string;
  is_dependency?: boolean;
  dependency_reason?: string;
}

export interface CloudPlan {
  provider: string;
  region: string;
  environment: string;
  resources: CloudResource[];
  outputs?: Record<string, string>;
}

export interface UniversalIR {
  intent: string;
  description?: string | null;
  database?: DatabaseSchema | null;
  cloud?: CloudPlan | null;
  dependencies?: string[];
  assumptions?: string[];
  estimated_cost_monthly?: number | null;
  risk_level?: string | null;
}

export interface SecurityCheck {
  rule_id: string;
  severity: 'LOW' | 'MEDIUM' | 'HIGH' | 'CRITICAL';
  resource: string;
  message: string;
  remediation: string;
}

export interface PlanResponse {
  plan_id: string;
  status: 'draft' | 'awaiting_approval' | 'pending_approval' | 'approved' | 'rejected' | 'executing' | 'completed' | 'failed' | string;
  intent: string;
  risk_level: 'low' | 'medium' | 'high' | 'critical';
  requires_confirmation_text: boolean;
  confirmation_phrase?: string | null;
  summary_preview: string;
  ir: UniversalIR;
  generated_terraform?: string | null;
  generated_sql?: string | null;
  estimated_cost_monthly: number;
  security_checks: SecurityCheck[];
  connection_id?: string | null;
  environment?: string;
  target_label?: string;
  account_id?: string;
  region?: string;
  website_url?: string;
  implementation_plan?: ImplementationStep[];
  created_at: string;
}

export interface ImplementationStep {
  step_number: number;
  name: string;
  phase: 'infra' | 'config' | 'content' | 'verify' | 'handoff' | string;
  description: string;
  status?: 'pending' | 'active' | 'completed' | 'failed' | string;
}

export interface ClarificationQuestion {
  question: string;
  context?: string;
  default_suggestion?: string;
  options?: string[];
  conflict_type?: string;
  resource_name?: string;
}

export interface ClarificationResponse {
  is_ready: boolean;
  questions: ClarificationQuestion[];
  raw_message?: string;
}

export interface EnvironmentSnapshot {
  snapshot_id: string;
  snapshot_hash: string;
  provider: string;
  region: string;
  timestamp: number;
  age_seconds?: number;
  is_stale?: boolean;
  counts: {
    buckets: number;
    vpcs: number;
    subnets: number;
    security_groups: number;
    rds_instances: number;
    iam_roles: number;
    managed_resources: number;
  };
  buckets?: string[];
  vpcs?: any[];
  subnets?: any[];
  security_groups?: any[];
  rds_instances?: any[];
}

export interface RagCitation {
  tag: string;
  title: string;
  domain: string;
  resource_type?: string;
  score: number;
}

export interface ChatResponse {
  status: 'clarification_needed' | 'plan_ready' | 'conversation' | 'error';
  message: string;
  clarification?: ClarificationResponse;
  plan?: PlanResponse;
  rag_citations?: RagCitation[];
  requirements_md?: string;
}

export interface RequirementsResponse {
  session_id: string;
  requirements_md: string;
  file_path?: string;
  updated_at: string;
}

export interface ExecutionResult {
  plan_id: string;
  success: boolean;
  status: string;
  run_number?: number;
  resources_created: number;
  resources_updated: number;
  resources_deleted: number;
  terraform_output?: string;
  sql_output?: string;
  error_message?: string;
  execution_time_seconds: number;
  recovery_options?: string[];
  created_resources?: string[];
  wire_traces_count?: number;
  three_leg_status?: string;
  website_url?: string;
  resource_checklist?: {
    name: string;
    type: string;
    present: boolean;
    functional_green: boolean;
    details: string;
    error?: string | null;
  }[];
}

export interface WireTraceItem {
  seq: number;
  ts: string;
  plan_id: string;
  execution_id?: number | null;
  connection_id?: string | null;
  account?: string | null;
  region?: string | null;
  service: string;
  operation: string;
  source: string;
  params_masked: Record<string, any>;
  http_status: number;
  error_code?: string | null;
  error_message?: string | null;
  request_id?: string | null;
  latency_ms: number;
  cloudtrail_confirmed?: boolean | null;
}

export interface WireTraceExportResponse {
  plan_id: string;
  traces_count: number;
  trace_hash: string;
  exported_at: string;
  traces: WireTraceItem[];
}

export interface ThreeLegVerificationReport {
  all_legs_agreed: boolean;
  overall_status: 'pass' | 'failed' | 'orphan_detected' | 'incident' | string;
  leg1_intent: Record<string, any>;
  leg2_wire: Record<string, any>;
  leg3_truth: Record<string, any>;
  zombie_events_detected: boolean;
  orphan_resources_detected: boolean;
  details: Record<string, any>;
}

export interface SupervisorEventResponse {
  seq: number;
  timestamp: string;
  plan_id: string;
  execution_id?: number | null;
  phase: 'MONITOR' | 'DETECT' | 'DECIDE' | 'ACT' | 'VERIFY' | 'AUDIT' | string;
  signature?: string | null;
  diagnosis?: string | null;
  decision?: string | null;
  confidence: number;
  reasoning?: string | null;
  message: string;
}

export interface ExecutionPolicy {
  on_failure: 'auto_destroy' | 'ask' | 'keep';
  on_cost_overrun: 'auto_destroy' | 'ask' | 'keep';
  max_heal_attempts: number;
  protected_resources: string;
}

export interface VerificationResult {
  plan_id: string;
  status: 'success' | 'drift_detected' | 'failed' | 'incident' | 'orphan_detected' | string;
  drift_detected: boolean;
  resources_verified: number;
  expected_resources: string[];
  found_resources: string[];
  missing_resources: string[];
  details: Record<string, any>;
  target_environment?: string;
  audited_account_id?: string;
  audited_region?: string;
  audited_target_label?: string;
  audited_at?: string;
  error_message?: string;
  three_leg?: ThreeLegVerificationReport | null;
}

export interface AuditLogEntry {
  id?: number;
  event_type: string;
  plan_id?: string;
  risk_level: string;
  action_by: string;
  payload_hash?: string;
  details: Record<string, any>;
  timestamp: string;
}

export interface PlanSummary {
  plan_id: string;
  prompt: string;
  intent: string;
  risk_level: 'low' | 'medium' | 'high' | 'critical';
  status: string;
  estimated_cost_monthly?: number;
  created_at?: string;
}

export interface ChatSession {
  id: string;
  title: string;
  status: 'active' | 'has-completed-plan' | 'completed' | 'failed' | string;
  message_count: number;
  last_plan_id?: string | null;
  created_at: string;
  updated_at: string;
  last_plan?: PlanResponse | null;
  requirements_md?: string;
}

export interface SessionMessage {
  id: string;
  session_id: string;
  role: 'user' | 'assistant' | 'system';
  content: string;
  plan_id?: string | null;
  created_at: string;
  clarification?: ClarificationResponse | null;
}

export interface ReexecuteResult {
  plan_id: string;
  status: 'noop' | 'drift_detected' | 'error';
  has_changes: boolean;
  message: string;
  diff: {
    missing?: string[];
    verified?: number;
    expected?: string[];
    found?: string[];
    [key: string]: any;
  };
  requires_confirmation_text: boolean;
  confirmation_phrase?: string | null;
}

export interface ExecutionRecordItem {
  id: number;
  plan_id: string;
  run_number: number;
  status: string;
  success: boolean;
  resources_created: number;
  resources_updated: number;
  resources_deleted: number;
  execution_time_seconds: number;
  error_message?: string | null;
  created_at: string;
}

export interface ErrorDetectionResponse {
  signature: string;
  error_class: string;
  message: string;
  is_unfixable: boolean;
  remediation_class: 'auto' | 'approve' | 'halted' | string;
  diagnosis?: string | null;
}

export interface HealingAttempt {
  id: number;
  execution_id?: number | null;
  plan_id: string;
  attempt_number: number;
  error_signature: string;
  error_class: string;
  error_message?: string | null;
  remediation_class: 'auto' | 'approve' | 'halted' | string;
  fix_type: string;
  root_cause?: string | null;
  reasoning?: string | null;
  confidence: number;
  risk_assessment: 'low' | 'medium' | 'high' | 'critical' | string;
  patch_data?: Record<string, any> | null;
  diff?: Record<string, any> | null;
  status: 'detected' | 'proposed' | 'awaiting_approval' | 'approved' | 'applied' | 'rejected' | 'halted' | 'failed' | string;
  is_auto_applied: boolean;
  created_at: string;
  updated_at?: string | null;
}

export interface RemediationKBItem {
  id: number;
  signature: string;
  error_class: string;
  fix_type: string;
  fix_template?: Record<string, any> | null;
  description?: string | null;
  success_count: number;
  failure_count: number;
  cross_plan_failures: number;
  enabled: boolean;
  is_promoted: boolean;
  circuit_broken: boolean;
  version: number;
  created_at: string;
  updated_at?: string | null;
}

// ========================================================
// M-17: Connection & Service Scope Types
// ========================================================

export interface Connection {
  id: string;
  name: string;
  provider: string;
  environment: 'local' | 'staging' | 'prod';
  auth_method: 'access_key' | 'profile';
  profile_name?: string | null;
  region: string;
  key_prefix?: string | null;
  key_last4?: string | null;
  masked_key?: string | null;
  services: string[];
  status: string; // 'connected' | 'untested' | 'error' | 'restart_pending'
  restart_pending: boolean;
  account_id?: string | null;
  arn?: string | null;
  last_tested_at?: string | null;
  created_at?: string | null;
  updated_at?: string | null;
}

export interface ServiceProbeResult {
  service: string;
  status: 'ok' | 'error';
  latency_ms: number;
  error?: string | null;
}

export interface ConnectionTestResult {
  account_id: string;
  arn: string;
  services: ServiceProbeResult[];
  overall_status: 'ok' | 'partial' | 'error';
}

export interface ConnectionFormData {
  name: string;
  provider: string;
  environment: 'local' | 'staging' | 'prod';
  auth_method: 'access_key' | 'profile';
  profile_name?: string;
  access_key_id?: string;
  secret_access_key?: string;
  region: string;
  services: string[];
  confirm_name?: string;
}



