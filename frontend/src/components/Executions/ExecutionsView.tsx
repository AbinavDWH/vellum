import React, { useState, useEffect } from 'react';
import { Terminal, Play, CheckCircle2, AlertCircle, RefreshCw, Layers, ExternalLink, ShieldCheck, Clock, Square } from 'lucide-react';
import { PlanSummary, ExecutionRecordItem } from '../../types';
import { api } from '../../services/api';
import { Button } from '../ui/Button';
import { Chip } from '../ui/Chip';
import { EmptyState } from '../ui/EmptyState';
import { Skeleton } from '../ui/Skeleton';
import { ExecutionConsole } from '../ExecutionProgress/ExecutionConsole';
import { useToast } from '../ui/Toast';
import { formatRelativeTime, cn } from '../../lib/utils';

export interface ExecutionsViewProps {
  activeExecutingPlanId: string | null;
  onClearExecutingPlan: () => void;
  onGoToDesigner: (planId?: string) => void;
  onViewAudit: () => void;
  onStartExecution: (planId: string) => void;
}

export const ExecutionsView: React.FC<ExecutionsViewProps> = ({
  activeExecutingPlanId,
  onClearExecutingPlan,
  onGoToDesigner,
  onViewAudit,
  onStartExecution,
}) => {
  const { toast } = useToast();
  const [plans, setPlans] = useState<PlanSummary[]>([]);
  const [executions, setExecutions] = useState<ExecutionRecordItem[]>([]);
  const [loading, setLoading] = useState(true);
  const [verifyingPlanId, setVerifyingPlanId] = useState<string | null>(null);
  const [rerunningPlanId, setRerunningPlanId] = useState<string | null>(null);
  const [terminatingRows, setTerminatingRows] = useState<Record<string, { stage: number; status: 'terminating' | 'terminated_reconciling' }>>({});

  const handleRowTerminate = async (execId: number | string, planId: string) => {
    const key = String(execId || planId);
    const current = terminatingRows[key] || { stage: 0, status: 'terminating' };
    if (current.stage === 0) {
      setTerminatingRows((prev) => ({
        ...prev,
        [key]: { stage: 1, status: 'terminating' },
      }));
      try {
        await api.terminateExecution(execId || planId, false);
        toast({
          title: 'Graceful Termination Sent',
          description: `SIGINT sent to execution ${key}. Click again to force kill.`,
          type: 'warn',
        });
      } catch (err: any) {
        toast({ title: 'Termination Failed', description: err.message, type: 'crit' });
      }
    } else {
      setTerminatingRows((prev) => ({
        ...prev,
        [key]: { stage: 2, status: 'terminated_reconciling' },
      }));
      try {
        await api.terminateExecution(execId || planId, true);
        toast({
          title: 'Force Kill Dispatched',
          description: `SIGKILL sent to execution ${key}. Process reaped and state reconciled.`,
          type: 'crit',
        });
        loadData();
      } catch (err: any) {
        toast({ title: 'Force Kill Failed', description: err.message, type: 'crit' });
      }
    }
  };

  const loadData = async () => {
    try {
      setLoading(true);
      const [plansData, execsData] = await Promise.all([
        api.getPlans(30).catch(() => []),
        api.getExecutions().catch(() => []),
      ]);
      setPlans(plansData);
      setExecutions(execsData);
    } catch (err) {
      console.error(err);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    if (!activeExecutingPlanId) {
      loadData();
    }
  }, [activeExecutingPlanId]);

  const handleVerify = async (planId: string) => {
    try {
      setVerifyingPlanId(planId);
      const res = await api.verifyPlan(planId);
      if (res.drift_detected || res.missing_resources?.length > 0) {
        toast({
          title: 'Drift Detected',
          description: `Missing: ${res.missing_resources?.join(', ') || 'drift found'}. Re-execution required.`,
          type: 'crit',
        });
      } else {
        toast({
          title: 'Verification Passed',
          description: `All ${res.resources_verified} resources verified healthy in target cloud.`,
          type: 'success',
        });
      }
    } catch (err: any) {
      toast({
        title: 'Verification Failed',
        description: err.message || 'Could not verify plan',
        type: 'crit',
      });
    } finally {
      setVerifyingPlanId(null);
    }
  };

  const handleRerun = async (planId: string) => {
    try {
      setRerunningPlanId(planId);
      const res = await api.reexecutePlan(planId);
      if (res.status === 'noop') {
        toast({
          title: 'No-Op Re-Execution',
          description: res.message || 'Infrastructure already matches plan. No changes made.',
          type: 'info',
        });
      } else if (res.status === 'drift_detected') {
        toast({
          title: 'Drift Detected (Dry-Run)',
          description: 'Changes detected. Loading plan in Designer for approval.',
          type: 'crit',
        });
        onGoToDesigner(planId);
      } else {
        onStartExecution(planId);
      }
      loadData();
    } catch (err: any) {
      toast({
        title: 'Re-execution Error',
        description: err.message || 'Could not re-execute plan',
        type: 'crit',
      });
    } finally {
      setRerunningPlanId(null);
    }
  };

  if (activeExecutingPlanId) {
    return (
      <ExecutionConsole
        planId={activeExecutingPlanId}
        onBackToDesigner={onClearExecutingPlan}
        onViewAudit={onViewAudit}
      />
    );
  }

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-xl font-bold tracking-tight text-ink-primary">Execution & Console</h1>
          <p className="text-xs text-ink-secondary">
            Execute approved plans against target cloud, inspect run history, and stream live Terraform logs
          </p>
        </div>
        <Button variant="primary" size="sm" onClick={() => onGoToDesigner()}>
          New Design
        </Button>
      </div>

      {loading ? (
        <div className="space-y-3">
          {[...Array(3)].map((_, i) => (
            <Skeleton key={i} className="h-20 w-full" />
          ))}
        </div>
      ) : executions.length === 0 && plans.length === 0 ? (
        <EmptyState
          icon={<Terminal className="h-6 w-6 text-brand" />}
          title="No executions recorded yet"
          hint="Generate and approve an infrastructure plan in the Designer to stream live Terraform logs and verification."
          actionLabel="Open Designer"
          onAction={() => onGoToDesigner()}
        />
      ) : (
        <div className="space-y-6">
          {/* Execution History with Run Numbers */}
          {executions.length > 0 && (
            <div className="space-y-3">
              <div className="text-xs font-semibold uppercase tracking-wider text-ink-tertiary flex items-center justify-between">
                <span>Execution History (M-13 Multi-Run)</span>
                <span className="text-[11px] font-normal lowercase">{executions.length} runs recorded</span>
              </div>

              {executions.map((exec) => (
                <div
                  key={`${exec.plan_id}-run-${exec.run_number}-${exec.id}`}
                  className="p-4 rounded-xl bg-surface border border-line flex flex-col sm:flex-row sm:items-center justify-between gap-4 transition-colors hover:border-line-hover"
                >
                  <div className="space-y-1">
                    <div className="flex items-center gap-2">
                      <span className="font-mono text-xs font-bold px-2 py-0.5 rounded bg-brand/10 text-brand border border-brand/20">
                        Run #{exec.run_number}
                      </span>
                      <button
                        onClick={() => onGoToDesigner(exec.plan_id)}
                        className="font-mono text-xs text-ink-primary hover:text-brand hover:underline cursor-pointer flex items-center gap-1"
                        title="Open parent plan in Designer"
                      >
                        {exec.plan_id}
                        <ExternalLink className="h-2.5 w-2.5" />
                      </button>
                      {(() => {
                        const rowKey = String(exec.id || exec.plan_id);
                        const rowTerm = terminatingRows[rowKey];
                        if (rowTerm?.status === 'terminating') {
                          return (
                            <span className="text-[10px] font-mono px-2 py-0.5 rounded border uppercase bg-amber-500/10 border-amber-500/30 text-amber-400 animate-pulse">
                              TERMINATING
                            </span>
                          );
                        }
                        if (rowTerm?.status === 'terminated_reconciling') {
                          return (
                            <span className="text-[10px] font-mono px-2 py-0.5 rounded border uppercase bg-rose-500/10 border-rose-500/30 text-rose-400">
                              TERMINATED/RECONCILING
                            </span>
                          );
                        }
                        const isRunning = exec.status === 'running' || exec.status === 'executing';
                        return (
                          <span
                            className={`text-[10px] font-mono px-2 py-0.5 rounded border uppercase ${
                              exec.status === 'completed'
                                ? 'bg-emerald-500/10 border-emerald-500/30 text-emerald-400'
                                : isRunning
                                ? 'bg-blue-500/10 border-blue-500/30 text-blue-400 animate-pulse'
                                : 'bg-rose-500/10 border-rose-500/30 text-rose-400'
                            }`}
                          >
                            {exec.status}
                          </span>
                        );
                      })()}
                    </div>

                    <div className="flex items-center gap-3 text-xs text-ink-secondary">
                      <span>Created: {exec.resources_created}</span>
                      <span>•</span>
                      <span>Time: {(exec.execution_time_seconds ?? (exec as any).duration_seconds ?? 0).toFixed(1)}s</span>
                      {exec.created_at && (
                        <>
                          <span>•</span>
                          <span className="text-[11px] text-ink-tertiary">
                            {formatRelativeTime(exec.created_at)}
                          </span>
                        </>
                      )}
                    </div>
                  </div>

                  <div className="flex items-center gap-2 shrink-0">
                    {(exec.status === 'running' || exec.status === 'executing' || terminatingRows[String(exec.id || exec.plan_id)]) && (
                      <Button
                        variant="destructive"
                        size="sm"
                        onClick={() => handleRowTerminate(exec.id, exec.plan_id)}
                        leftIcon={<Square className="h-3 w-3 fill-current" />}
                        className={cn(
                          'bg-crit hover:bg-crit/90 text-white font-medium',
                          terminatingRows[String(exec.id || exec.plan_id)]?.status === 'terminating' &&
                            'animate-pulse bg-warn hover:bg-warn/90 text-ink-primary'
                        )}
                        aria-label={
                          terminatingRows[String(exec.id || exec.plan_id)]?.status === 'terminating'
                            ? 'Force Kill execution'
                            : 'Terminate execution'
                        }
                      >
                        {terminatingRows[String(exec.id || exec.plan_id)]?.status === 'terminating'
                          ? '⏹ Force Kill (Click 2)'
                          : '⏹ Terminate'}
                      </Button>
                    )}

                    <Button
                      variant="secondary"
                      size="sm"
                      onClick={() => handleRerun(exec.plan_id)}
                      disabled={rerunningPlanId === exec.plan_id}
                      loading={rerunningPlanId === exec.plan_id}
                      leftIcon={<RefreshCw className="h-3.5 w-3.5" />}
                    >
                      Re-run
                    </Button>

                    <Button
                      variant="ghost"
                      size="sm"
                      onClick={() => handleVerify(exec.plan_id)}
                      disabled={verifyingPlanId === exec.plan_id}
                      loading={verifyingPlanId === exec.plan_id}
                      leftIcon={<ShieldCheck className="h-3.5 w-3.5 text-brand" />}
                    >
                      Verify now
                    </Button>

                    <Button
                      variant="primary"
                      size="sm"
                      onClick={() => onStartExecution(exec.plan_id)}
                      leftIcon={<Terminal className="h-3.5 w-3.5" />}
                    >
                      Logs
                    </Button>
                  </div>
                </div>
              ))}
            </div>
          )}

          {/* Recent Plans Ready for Execution */}
          {plans.length > 0 && (
            <div className="space-y-3 pt-2">
              <div className="text-xs font-semibold uppercase tracking-wider text-ink-tertiary">
                Recent Plans in Registry
              </div>
              {plans.map((p) => (
                <div
                  key={p.plan_id}
                  className="p-4 rounded-xl bg-surface border border-line flex flex-col sm:flex-row sm:items-center justify-between gap-4"
                >
                  <div className="space-y-1">
                    <div className="flex items-center gap-2">
                      <button
                        onClick={() => onGoToDesigner(p.plan_id)}
                        className="font-mono text-xs font-semibold text-brand hover:underline cursor-pointer flex items-center gap-1"
                      >
                        {p.plan_id}
                        <ExternalLink className="h-2.5 w-2.5" />
                      </button>
                      <Chip risk={p.risk_level} showRiskIcon />
                      {(() => {
                        const rowTerm = terminatingRows[p.plan_id];
                        if (rowTerm?.status === 'terminating') {
                          return (
                            <span className="text-[10px] font-mono px-2 py-0.5 rounded border uppercase bg-amber-500/10 border-amber-500/30 text-amber-400 animate-pulse">
                              TERMINATING
                            </span>
                          );
                        }
                        if (rowTerm?.status === 'terminated_reconciling') {
                          return (
                            <span className="text-[10px] font-mono px-2 py-0.5 rounded border uppercase bg-rose-500/10 border-rose-500/30 text-rose-400">
                              TERMINATED/RECONCILING
                            </span>
                          );
                        }
                        return (
                          <span className="text-[10px] font-mono px-2 py-0.5 rounded bg-elevated border border-line text-ink-secondary uppercase">
                            {p.status}
                          </span>
                        );
                      })()}
                    </div>
                    <h3 className="text-xs font-medium text-ink-primary truncate max-w-xl">
                      {p.prompt || p.intent}
                    </h3>
                    {p.created_at && (
                      <span className="text-[11px] text-ink-tertiary">
                        Created {formatRelativeTime(p.created_at)}
                      </span>
                    )}
                  </div>

                  <div className="flex items-center gap-2 shrink-0">
                    {(p.status === 'running' || p.status === 'executing' || terminatingRows[p.plan_id]) && (
                      <Button
                        variant="destructive"
                        size="sm"
                        onClick={() => handleRowTerminate(p.plan_id, p.plan_id)}
                        leftIcon={<Square className="h-3 w-3 fill-current" />}
                        className={cn(
                          'bg-crit hover:bg-crit/90 text-white font-medium',
                          terminatingRows[p.plan_id]?.status === 'terminating' &&
                            'animate-pulse bg-warn hover:bg-warn/90 text-ink-primary'
                        )}
                        aria-label="Terminate execution"
                      >
                        {terminatingRows[p.plan_id]?.status === 'terminating'
                          ? '⏹ Force Kill (Click 2)'
                          : '⏹ Terminate'}
                      </Button>
                    )}

                    <Button
                      variant="secondary"
                      size="sm"
                      onClick={() => onStartExecution(p.plan_id)}
                      leftIcon={<Terminal className="h-3.5 w-3.5 text-brand" />}
                    >
                      View Console
                    </Button>
                  </div>
                </div>
              ))}
            </div>
          )}
        </div>
      )}
    </div>
  );
};
