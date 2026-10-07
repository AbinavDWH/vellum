import {
  ChatResponse,
  PlanResponse,
  ExecutionResult,
  VerificationResult,
  AuditLogEntry,
  PlanSummary,
  ChatSession,
  SessionMessage,
  ReexecuteResult,
  ExecutionRecordItem,
  ErrorDetectionResponse,
  HealingAttempt,
  RemediationKBItem,
  EnvironmentSnapshot,
  Connection,
  ConnectionTestResult,
  ConnectionFormData,
  RequirementsResponse,
  WireTraceItem,
  WireTraceExportResponse,
  SupervisorEventResponse,
} from '../types';

const API_BASE = '/api';

export const api = {
  async stopChat(sessionId: string): Promise<{ status: string; session_id: string }> {
    const res = await fetch(`${API_BASE}/chat/stop/${sessionId}`, {
      method: 'POST',
    });
    if (!res.ok) {
      return this.cancelChat(sessionId);
    }
    return res.json();
  },

  async cancelChat(sessionId: string): Promise<{ status: string; session_id: string }> {
    const res = await fetch(`${API_BASE}/chat/cancel`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ session_id: sessionId }),
    });
    if (!res.ok) throw new Error('Failed to cancel chat');
    return res.json();
  },
  async getHealth() {
    const res = await fetch(`${API_BASE}/health`);
    if (!res.ok) throw new Error('Health check failed');
    return res.json();
  },

  async getModels() {
    const res = await fetch(`${API_BASE}/models`);
    if (!res.ok) throw new Error('Failed to fetch models');
    return res.json();
  },

  async getActiveAI() {
    const res = await fetch(`${API_BASE}/ai/active`);
    if (!res.ok) throw new Error('Failed to fetch active AI');
    return res.json();
  },

  async setActiveAI(provider: 'groq' | 'local', model?: string) {
    const res = await fetch(`${API_BASE}/ai/active`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ provider, model }),
    });
    if (!res.ok) {
      const err = await res.json().catch(() => ({ detail: 'Failed to set active AI' }));
      throw new Error(err.detail || 'Failed to set active AI');
    }
    return res.json();
  },

  // Sessions CRUD (M-13)
  async getSessions(search?: string): Promise<ChatSession[]> {
    const url = search ? `${API_BASE}/sessions?search=${encodeURIComponent(search)}` : `${API_BASE}/sessions`;
    const res = await fetch(url);
    if (!res.ok) throw new Error('Failed to fetch sessions');
    return res.json();
  },

  async createSession(title?: string, provider?: string, environment?: string): Promise<ChatSession> {
    const payload: Record<string, string> = {};
    if (title) payload.title = title;
    if (provider) payload.cloud_provider = provider;
    if (environment) payload.environment = environment;
    const res = await fetch(`${API_BASE}/sessions`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    });
    if (!res.ok) throw new Error('Failed to create session');
    return res.json();
  },

  async getSession(sessionId: string): Promise<ChatSession & { last_plan?: PlanResponse }> {
    const res = await fetch(`${API_BASE}/sessions/${sessionId}`);
    if (!res.ok) throw new Error('Failed to fetch session details');
    return res.json();
  },

  async getSessionMessages(sessionId: string): Promise<SessionMessage[]> {
    const res = await fetch(`${API_BASE}/sessions/${sessionId}/messages`);
    if (!res.ok) throw new Error('Failed to fetch session messages');
    return res.json();
  },

  async renameSession(sessionId: string, title: string): Promise<ChatSession> {
    const res = await fetch(`${API_BASE}/sessions/${sessionId}`, {
      method: 'PATCH',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ title }),
    });
    if (!res.ok) throw new Error('Failed to rename session');
    return res.json();
  },

  async deleteSession(sessionId: string): Promise<{ status: string; id: string }> {
    const res = await fetch(`${API_BASE}/sessions/${sessionId}`, {
      method: 'DELETE',
    });
    if (!res.ok) throw new Error('Failed to delete session');
    return res.json();
  },

  async getSessionRequirements(sessionId: string): Promise<RequirementsResponse> {
    const res = await fetch(`${API_BASE}/sessions/${sessionId}/requirements`);
    if (!res.ok) throw new Error('Failed to fetch session requirements specification');
    return res.json();
  },

  async updateSessionRequirements(sessionId: string, requirementsMd: string): Promise<RequirementsResponse> {
    const res = await fetch(`${API_BASE}/sessions/${sessionId}/requirements`, {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ requirements_md: requirementsMd }),
    });
    if (!res.ok) throw new Error('Failed to update requirements specification');
    return res.json();
  },

  async planFromRequirements(sessionId: string, cloudProvider = 'aws', environment = 'local'): Promise<ChatResponse> {
    const res = await fetch(`${API_BASE}/sessions/${sessionId}/plan-from-requirements?cloud_provider=${encodeURIComponent(cloudProvider)}&environment=${encodeURIComponent(environment)}`, {
      method: 'POST',
    });
    if (!res.ok) throw new Error('Failed to synthesize plan from requirements specification');
    return res.json();
  },

  async sendChat(
    prompt: string,
    sessionId?: string,
    model?: string,
    cloudProvider = 'aws',
    environment = 'local'
  ): Promise<ChatResponse> {
    const res = await fetch(`${API_BASE}/chat`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        prompt,
        session_id: sessionId,
        model,
        cloud_provider: cloudProvider,
        environment,
      }),
    });
    if (!res.ok) {
      const err = await res.json().catch(() => ({ detail: 'Chat request failed' }));
      throw new Error(err.detail || 'Chat request failed');
    }
    return res.json();
  },

  async getPlan(planId: string): Promise<PlanResponse> {
    const res = await fetch(`${API_BASE}/plans/${planId}`);
    if (!res.ok) throw new Error('Failed to fetch plan');
    return res.json();
  },

  async submitApproval(
    planId: string,
    decision: 'approve' | 'reject' | 'modify',
    options?: {
      confirmationText?: string;
      modifications?: string;
      customTerraform?: string;
      customSql?: string;
    }
  ) {
    const res = await fetch(`${API_BASE}/plans/${planId}/approval`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        decision,
        confirmation_text: options?.confirmationText,
        modifications: options?.modifications,
        custom_terraform: options?.customTerraform,
        custom_sql: options?.customSql,
      }),
    });
    if (!res.ok) {
      const err = await res.json().catch(() => ({ detail: 'Approval submission failed' }));
      throw new Error(err.detail || 'Approval submission failed');
    }
    return res.json();
  },

  async executePlan(planId: string): Promise<ExecutionResult> {
    const res = await fetch(`${API_BASE}/plans/${planId}/execute`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
    });
    if (!res.ok) {
      const err = await res.json().catch(() => ({ detail: 'Execution failed' }));
      throw new Error(err.detail || 'Execution failed');
    }
    return res.json();
  },

  async reexecutePlan(planId: string, idempotencyKey?: string): Promise<ReexecuteResult> {
    const headers: Record<string, string> = { 'Content-Type': 'application/json' };
    if (idempotencyKey) {
      headers['Idempotency-Key'] = idempotencyKey;
    }
    const res = await fetch(`${API_BASE}/plans/${planId}/re-execute`, {
      method: 'POST',
      headers,
      body: JSON.stringify(idempotencyKey ? { idempotency_key: idempotencyKey } : {}),
    });
    if (!res.ok) {
      const err = await res.json().catch(() => ({ detail: 'Re-execution failed' }));
      throw new Error(err.detail || 'Re-execution failed');
    }
    return res.json();
  },

  async getExecutions(planId?: string): Promise<ExecutionRecordItem[]> {
    const url = planId ? `${API_BASE}/plans/${planId}/executions` : `${API_BASE}/executions`;
    const res = await fetch(url);
    if (!res.ok) throw new Error('Failed to fetch executions');
    return res.json();
  },

  async getChatHistory(sessionId = 'default'): Promise<{ session_id: string; messages: any[] }> {
    const res = await fetch(`${API_BASE}/chat/history?session_id=${encodeURIComponent(sessionId)}`);
    if (!res.ok) throw new Error('Failed to fetch chat history');
    return res.json();
  },

  async clearChatHistory(sessionId = 'default'): Promise<{ status: string }> {
    const res = await fetch(`${API_BASE}/chat/history?session_id=${encodeURIComponent(sessionId)}`, {
      method: 'DELETE',
    });
    if (!res.ok) throw new Error('Failed to clear chat history');
    return res.json();
  },

  async verifyPlan(planId: string): Promise<VerificationResult> {
    const res = await fetch(`${API_BASE}/plans/${planId}/verify`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
    });
    if (!res.ok) {
      const err = await res.json().catch(() => ({ detail: 'Verification failed' }));
      throw new Error(err.detail || 'Verification failed');
    }
    return res.json();
  },

  async rollbackPlan(planId: string): Promise<ExecutionResult> {
    const res = await fetch(`${API_BASE}/plans/${planId}/rollback`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
    });
    if (!res.ok) {
      const err = await res.json().catch(() => ({ detail: 'Rollback failed' }));
      throw new Error(err.detail || 'Rollback failed');
    }
    return res.json();
  },

  async getPlanTraces(planId: string): Promise<WireTraceItem[]> {
    const res = await fetch(`${API_BASE}/plans/${planId}/traces`);
    if (!res.ok) throw new Error('Failed to fetch wire traces');
    return res.json();
  },

  async exportPlanTraces(planId: string): Promise<WireTraceExportResponse> {
    const res = await fetch(`${API_BASE}/plans/${planId}/traces/export`);
    if (!res.ok) throw new Error('Failed to export wire traces');
    return res.json();
  },

  async getSupervisorFeed(planId: string): Promise<SupervisorEventResponse[]> {
    const res = await fetch(`${API_BASE}/plans/${planId}/supervisor/feed`);
    if (!res.ok) throw new Error('Failed to fetch supervisor feed');
    return res.json();
  },

  async terminateExecution(executionIdOrPlanId: string | number, force = false): Promise<{ status: string; mode: string }> {
    const res = await fetch(`${API_BASE}/executions/${executionIdOrPlanId}/terminate`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ force }),
    });
    if (!res.ok) {
      const err = await res.json().catch(() => ({ detail: 'Terminate failed' }));
      throw new Error(err.detail || 'Terminate failed');
    }
    return res.json();
  },

  async terminatePlan(planId: string, force = false): Promise<{ status: string; mode: string }> {
    return this.terminateExecution(planId, force);
  },

  async getAuditLogs(): Promise<AuditLogEntry[]> {
    const res = await fetch(`${API_BASE}/audit`);
    if (!res.ok) throw new Error('Failed to fetch audit logs');
    return res.json();
  },

  async getPlans(limit = 20): Promise<PlanSummary[]> {
    const res = await fetch(`${API_BASE}/plans?limit=${limit}`);
    if (!res.ok) throw new Error('Failed to fetch plans');
    return res.json();
  },

  // M-14: Self-Healing & Remediation APIs
  async getExecutionErrors(id: string | number): Promise<ErrorDetectionResponse[]> {
    const res = await fetch(`${API_BASE}/executions/${id}/errors`);
    if (!res.ok) throw new Error('Failed to fetch execution errors');
    return res.json();
  },

  async getExecutionHeals(id: string | number): Promise<HealingAttempt[]> {
    const res = await fetch(`${API_BASE}/executions/${id}/heals`);
    if (!res.ok) throw new Error('Failed to fetch healing attempts');
    return res.json();
  },

  async approveHeal(id: string | number, attemptNumber: number): Promise<any> {
    const res = await fetch(`${API_BASE}/executions/${id}/heals/${attemptNumber}/approve`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
    });
    if (!res.ok) {
      const err = await res.json().catch(() => ({ detail: 'Failed to approve heal' }));
      throw new Error(err.detail || 'Failed to approve heal');
    }
    return res.json();
  },

  async rejectHeal(id: string | number, attemptNumber: number): Promise<any> {
    const res = await fetch(`${API_BASE}/executions/${id}/heals/${attemptNumber}/reject`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
    });
    if (!res.ok) {
      const err = await res.json().catch(() => ({ detail: 'Failed to reject heal' }));
      throw new Error(err.detail || 'Failed to reject heal');
    }
    return res.json();
  },

  async getRemediations(): Promise<RemediationKBItem[]> {
    const res = await fetch(`${API_BASE}/remediations`);
    if (!res.ok) throw new Error('Failed to fetch remediation KB');
    return res.json();
  },

  async updateRemediation(
    id: number,
    data: { enabled?: boolean; description?: string }
  ): Promise<RemediationKBItem> {
    const res = await fetch(`${API_BASE}/remediations/${id}`, {
      method: 'PATCH',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(data),
    });
    if (!res.ok) {
      const err = await res.json().catch(() => ({ detail: 'Failed to update remediation KB entry' }));
      throw new Error(err.detail || 'Failed to update remediation KB entry');
    }
    return res.json();
  },

  // Environment Introspection (M-15)
  async getEnvironmentSnapshot(forceRescan = false): Promise<EnvironmentSnapshot> {
    const url = forceRescan ? `${API_BASE}/environment/snapshot?force_rescan=true` : `${API_BASE}/environment/snapshot`;
    const res = await fetch(url);
    if (!res.ok) throw new Error('Failed to fetch environment snapshot');
    return res.json();
  },

  async rescanEnvironment(): Promise<EnvironmentSnapshot> {
    const res = await fetch(`${API_BASE}/environment/rescan`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
    });
    if (!res.ok) throw new Error('Failed to rescan environment');
    return res.json();
  },

  // Connections & Credential Management (M-17)
  async getConnections(): Promise<Connection[]> {
    const res = await fetch(`${API_BASE}/connections`);
    if (!res.ok) throw new Error('Failed to fetch connections');
    return res.json();
  },

  async getConnection(id: string): Promise<Connection> {
    const res = await fetch(`${API_BASE}/connections/${id}`);
    if (!res.ok) throw new Error('Failed to fetch connection');
    return res.json();
  },

  async createConnection(data: Partial<ConnectionFormData>): Promise<Connection> {
    const res = await fetch(`${API_BASE}/connections`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(data),
    });
    if (!res.ok) {
      const err = await res.json().catch(() => ({ detail: 'Failed to create connection' }));
      throw new Error(err.detail || 'Failed to create connection');
    }
    return res.json();
  },

  async updateConnection(id: string, data: Partial<ConnectionFormData> & { acknowledge?: boolean }): Promise<Connection> {
    const res = await fetch(`${API_BASE}/connections/${id}`, {
      method: 'PATCH',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(data),
    });
    if (!res.ok) {
      const err = await res.json().catch(() => ({ detail: 'Failed to update connection' }));
      const error: any = new Error(err.detail || 'Failed to update connection');
      error.status = res.status;
      error.detail = err.detail;
      throw error;
    }
    return res.json();
  },

  async deleteConnection(id: string): Promise<{ deleted: boolean; connection_id: string }> {
    const res = await fetch(`${API_BASE}/connections/${id}`, {
      method: 'DELETE',
    });
    if (!res.ok) throw new Error('Failed to delete connection');
    return res.json();
  },

  async testConnection(id?: string, data?: Partial<ConnectionFormData>): Promise<ConnectionTestResult> {
    const url = id ? `${API_BASE}/connections/${id}/test` : `${API_BASE}/connections/test`;
    const res = await fetch(url, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: data ? JSON.stringify(data) : undefined,
    });
    if (!res.ok) {
      const err = await res.json().catch(() => ({ detail: 'Connection test failed' }));
      throw new Error(err.detail || 'Connection test failed');
    }
    return res.json();
  },

  async updateConnectionServices(id: string, services: string[], acknowledge = false): Promise<any> {
    const res = await fetch(`${API_BASE}/connections/${id}/services`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ services, acknowledge }),
    });
    if (!res.ok) {
      const err = await res.json().catch(() => ({ detail: 'Failed to update services' }));
      const error: any = new Error(err.detail || 'Failed to update services');
      error.status = res.status;
      throw error;
    }
    return res.json();
  },

  async restartLocalStack(): Promise<{ status: string; running_services: string[]; message: string }> {
    const res = await fetch(`${API_BASE}/localstack/restart`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
    });
    if (!res.ok) throw new Error('Failed to restart LocalStack');
    return res.json();
  },
};


