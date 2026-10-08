import React, { useEffect, useRef, useState, useMemo } from 'react';
import {
  Terminal,
  CheckCircle2,
  AlertCircle,
  Loader2,
  RefreshCw,
  Search,
  Check,
  AlertTriangle,
  ArrowLeft,
  Copy,
  Download,
  ShieldCheck,
  RotateCcw,
  ExternalLink,
  ShieldAlert,
  SlidersHorizontal,
  Square,
  Activity,
  Clock,
  FileJson,
  AlertOctagon,
  Info,
  Eye,
} from 'lucide-react';
import {
  ExecutionResult,
  VerificationResult,
  HealingAttempt,
  ErrorDetectionResponse,
  WireTraceItem,
  SupervisorEventResponse,
} from '../../types';
import { api } from '../../services/api';
import { Button } from '../ui/Button';
import { Chip } from '../ui/Chip';
import { Modal } from '../ui/Modal';
import { CopyButton } from '../ui/CopyButton';
import { useToast } from '../ui/Toast';
import { cn } from '../../lib/utils';
import { Wrench, Sparkles, ChevronDown, ChevronUp, History, GitCompare, X, Layers, Radio, Filter, ListChecks } from 'lucide-react';

export interface ExecutionConsoleProps {
  planId: string;
  onBackToDesigner: () => void;
  onViewAudit?: () => void;
}

type StageStatus = 'pending' | 'active' | 'done' | 'failed';

interface Stage {
  id: string;
  name: string;
  status: StageStatus;
  detail?: string;
}

export const ExecutionConsole: React.FC<ExecutionConsoleProps> = ({
  planId,
  onBackToDesigner,
  onViewAudit,
}) => {
  const { toast } = useToast();
  const [logs, setLogs] = useState<string[]>([]);
  const [executing, setExecuting] = useState(true);
  const [executionResult, setExecutionResult] = useState<ExecutionResult | null>(null);
  const [verificationResult, setVerificationResult] = useState<VerificationResult | null>(null);
  const [verifying, setVerifying] = useState(false);
  const [errorMessage, setErrorMessage] = useState<string | null>(null);
  const [planDetails, setPlanDetails] = useState<any>(null);

  useEffect(() => {
    api.getPlan(planId).then(setPlanDetails).catch(() => {});
  }, [planId]);

  const targetEnv = planDetails?.environment || planDetails?.ir?.cloud?.environment || 'local';
  const targetProvider = (planDetails?.ir?.cloud?.provider || 'aws').toUpperCase();
  const isLocal = targetEnv === 'local';
  const targetLabel = planDetails?.target_label || (isLocal ? 'LocalStack (Simulation)' : `${targetProvider} Cloud (${targetEnv.toUpperCase()})` + (planDetails?.account_id ? ` • Account: ${planDetails.account_id}` : '') + (planDetails?.region ? ` (${planDetails.region})` : ''));

  // M-14 Self-Healing state
  const [healingAttempts, setHealingAttempts] = useState<HealingAttempt[]>([]);
  const [currentDetectedError, setCurrentDetectedError] = useState<ErrorDetectionResponse | null>(null);
  const [currentAttemptNumber, setCurrentAttemptNumber] = useState<number>(1);
  const [expandedDiffs, setExpandedDiffs] = useState<Record<number, boolean>>({});
  const [approvingHealId, setApprovingHealId] = useState<number | null>(null);
  const [rejectingHealId, setRejectingHealId] = useState<number | null>(null);

  // M-19 & M-20 Console Tabs, Traces, Supervisor, and Terminate controls
  const [activeTab, setActiveTab] = useState<'terminal' | 'trace' | 'supervisor' | 'three_leg' | 'checklist'>('terminal');
  const [traces, setTraces] = useState<WireTraceItem[]>([]);
  const [tracesLoading, setTracesLoading] = useState(false);
  const [exportingTrace, setExportingTrace] = useState(false);
  const [traceFilter, setTraceFilter] = useState<'ALL' | 'FAILED' | 'S3' | 'EC2' | 'TERRAFORM'>('ALL');
  const [supervisorFeed, setSupervisorFeed] = useState<SupervisorEventResponse[]>([]);
  const [supervisorLoading, setSupervisorLoading] = useState(false);
  const [showTerminateModal, setShowTerminateModal] = useState(false);
  const [terminating, setTerminating] = useState(false);
  const [terminateState, setTerminateState] = useState<'idle' | 'terminating' | 'terminated_reconciling'>('idle');
  const [terminateClickCount, setTerminateClickCount] = useState<number>(0);
  const [selectedTrace, setSelectedTrace] = useState<WireTraceItem | null>(null);

  const filteredTraces = useMemo(() => {
    if (traceFilter === 'ALL') return traces;
    if (traceFilter === 'FAILED') return traces.filter((t) => t.http_status >= 400 || Boolean(t.error_code));
    if (traceFilter === 'S3') return traces.filter((t) => t.service.toLowerCase() === 's3');
    if (traceFilter === 'EC2') return traces.filter((t) => t.service.toLowerCase() === 'ec2');
    if (traceFilter === 'TERRAFORM') return traces.filter((t) => t.source === 'terraform');
    return traces;
  }, [traces, traceFilter]);

  const traceStats = useMemo(() => {
    const total = traces.length;
    const failed = traces.filter((t) => t.http_status >= 400 || Boolean(t.error_code)).length;
    const confirmed = traces.filter((t) => t.cloudtrail_confirmed === true).length;
    const s3Count = traces.filter((t) => t.service.toLowerCase() === 's3').length;
    const ec2Count = traces.filter((t) => t.service.toLowerCase() === 'ec2').length;
    return { total, failed, confirmed, s3Count, ec2Count };
  }, [traces]);

  useEffect(() => {
    if (activeTab === 'trace') {
      loadTraces();
    } else if (activeTab === 'supervisor') {
      loadSupervisor();
    }
  }, [activeTab, planId]);

  useEffect(() => {
    if (!executing) return;
    const interval = setInterval(() => {
      if (activeTab === 'trace') {
        loadTraces();
      } else if (activeTab === 'supervisor') {
        loadSupervisor();
      }
    }, 3000);
    return () => clearInterval(interval);
  }, [executing, activeTab, planId]);

  const loadTraces = async () => {
    setTracesLoading(true);
    try {
      const data = await api.getPlanTraces(planId);
      setTraces(data);
    } catch {
    } finally {
      setTracesLoading(false);
    }
  };

  const loadSupervisor = async () => {
    setSupervisorLoading(true);
    try {
      const data = await api.getSupervisorFeed(planId);
      setSupervisorFeed(data);
    } catch {
    } finally {
      setSupervisorLoading(false);
    }
  };

  const handleTerminate = async (force = false) => {
    setTerminating(true);
    setTerminateState(force ? 'terminated_reconciling' : 'terminating');
    try {
      const res = await api.terminatePlan(planId, force);
      toast({
        title: force ? 'Force Killed' : 'Gracefully Terminated',
        description: `Execution process stopped (${res.mode.toUpperCase()}). State reconciled.`,
        type: 'warn',
      });
      setShowTerminateModal(false);
      setExecuting(false);
      setErrorMessage(`Execution terminated by operator (${res.mode.toUpperCase()}).`);
      setLogs((prev) => [
        ...prev,
        `[WARN] [Operator Action] Execution process terminated (${res.mode.toUpperCase()}). State reconciled.`,
      ]);
      runVerification();
    } catch (e: any) {
      toast({
        title: 'Termination Failed',
        description: e.message || 'Failed to terminate process',
        type: 'crit',
      });
    } finally {
      setTerminating(false);
    }
  };

  const handleHeaderTerminateClick = async () => {
    if (terminateClickCount === 0) {
      setTerminateClickCount(1);
      setTerminateState('terminating');
      setTerminating(true);
      try {
        const res = await api.terminatePlan(planId, false);
        toast({
          title: 'Graceful Stop Sent (SIGINT)',
          description: 'Terraform is finishing state writes. Click again to force kill immediately.',
          type: 'warn',
        });
        setLogs((prev) => [
          ...prev,
          `[WARN] [Operator Action] Graceful stop requested (SIGINT). Click again to force kill immediately.`,
        ]);
      } catch (e: any) {
        toast({
          title: 'Graceful Stop Failed',
          description: e.message,
          type: 'crit',
        });
      } finally {
        setTerminating(false);
      }
    } else {
      setTerminateState('terminated_reconciling');
      await handleTerminate(true);
    }
  };

  const handleExportTraces = async () => {
    setExportingTrace(true);
    try {
      const exp = await api.exportPlanTraces(planId);
      const blob = new Blob([JSON.stringify(exp, null, 2)], { type: 'application/json' });
      const url = URL.createObjectURL(blob);
      const a = document.createElement('a');
      a.href = url;
      a.download = `vellum-wire-trace-${planId}.json`;
      document.body.appendChild(a);
      a.click();
      a.remove();
      URL.revokeObjectURL(url);
      toast({
        title: 'Exported & Verified (SHA-256)',
        description: `SHA-256: ${exp.trace_hash.substring(0, 16)}...`,
        type: 'success',
      });
    } catch (e: any) {
      toast({
        title: 'Export Failed',
        description: e.message,
        type: 'crit',
      });
    } finally {
      setExportingTrace(false);
    }
  };

  // Terminal view controls
  const [autoScroll, setAutoScroll] = useState(true);
  const [wrapText, setWrapText] = useState(true);
  const [logFilter, setLogFilter] = useState<'ALL' | 'INFO' | 'WARN' | 'ERROR'>('ALL');
  const [reexecuteCounter, setReexecuteCounter] = useState(0);
  const terminalContainerRef = useRef<HTMLDivElement>(null);
  const terminalEndRef = useRef<HTMLDivElement>(null);


  // Rollback confirmation modal
  const [showRollbackModal, setShowRollbackModal] = useState(false);
  const [rollbackInput, setRollbackInput] = useState('');
  const [rollingBack, setRollingBack] = useState(false);

  // Pipeline stages
  const stages = useMemo<Stage[]>(() => {
    const isExecDone = executionResult?.success === true;
    const isExecFailed = !isExecDone && (errorMessage !== null || (executionResult && !executionResult.success));
    const isVerifyDone = verificationResult !== null;

    return [
      { id: '1', name: 'Understand', status: 'done', detail: 'NLP parsed' },
      { id: '2', name: 'Plan', status: 'done', detail: 'IR generated' },
      { id: '3', name: 'Validate', status: 'done', detail: 'Policy checked' },
      { id: '4', name: 'Approve', status: 'done', detail: 'Human approved' },
      {
        id: '5',
        name: 'Execute',
        status: isExecFailed ? 'failed' : isExecDone ? 'done' : executing ? 'active' : 'pending',
        detail: executing ? 'Applying HCL' : isExecFailed ? 'Failed' : 'Applied',
      },
      {
        id: '6',
        name: 'Verify',
        status: verifying
          ? 'active'
          : isVerifyDone
          ? verificationResult.drift_detected
            ? 'failed'
            : 'done'
          : 'pending',
        detail: verifying ? 'Auditing state' : isVerifyDone ? 'Audited' : 'Pending',
      },
    ];
  }, [executing, executionResult, verificationResult, verifying, errorMessage]);

  // Implementation Plan Steps mapped to live progress (F7: infra -> config -> content -> verify -> handoff)
  const implementationSteps = useMemo(() => {
    const rawSteps = planDetails?.implementation_plan || planDetails?.ir?.implementation_plan || [];
    if (!rawSteps || rawSteps.length === 0) return [];

    const isExecDone = executionResult?.success === true;
    const isExecFailed = !isExecDone && (errorMessage !== null || (executionResult && !executionResult.success));
    const isVerifyDone = verificationResult !== null;
    const isVerifyFailed = isVerifyDone && (verificationResult.drift_detected || verificationResult.status !== 'success');

    // Latest supervisor decision for agent context
    const latestDecision = supervisorFeed.length > 0 ? supervisorFeed[supervisorFeed.length - 1] : null;

    return rawSteps.map((s: any) => {
      let status: 'pending' | 'active' | 'done' | 'failed' = 'pending';
      let agentDecision: string | undefined = undefined;

      if (s.phase === 'infra') {
        if (executing) {
          status = 'active';
        } else if (isExecDone || isVerifyDone) {
          status = 'done';
        } else if (isExecFailed) {
          status = 'failed';
          agentDecision = latestDecision?.decision || latestDecision?.message || 'Infra provisioning failed';
        }
      } else if (s.phase === 'config') {
        if (executing) {
          status = 'active';
        } else if (isExecDone || isVerifyDone) {
          status = 'done';
        } else if (isExecFailed) {
          status = 'failed';
          agentDecision = latestDecision?.decision || latestDecision?.message || 'Configuration error';
        }
      } else if (s.phase === 'content') {
        if (executing) {
          status = 'pending';
        } else if (isExecDone || isVerifyDone) {
          status = 'done';
        } else if (isExecFailed) {
          status = executionResult?.error_message?.toLowerCase().includes('sync') ? 'failed' : 'pending';
          if (status === 'failed') {
            agentDecision = latestDecision?.decision || 'Content synchronization failed';
          }
        }
      } else if (s.phase === 'verify') {
        if (verifying) {
          status = 'active';
        } else if (isVerifyDone && !isVerifyFailed && isExecDone) {
          status = 'done';
        } else if (isVerifyFailed || (isExecDone && verificationResult?.status !== 'success')) {
          status = 'failed';
          agentDecision = latestDecision?.decision || 'Functional verification check failed (HTTP/Head/Route check)';
        } else if (isExecFailed) {
          status = 'pending';
        }
      } else if (s.phase === 'handoff') {
        if (isExecDone && isVerifyDone && !isVerifyFailed) {
          status = 'done';
        } else if (isExecFailed || isVerifyFailed) {
          status = 'pending';
        }
      }

      return {
        ...s,
        status,
        agentDecision,
      };
    });
  }, [planDetails, executing, verifying, executionResult, verificationResult, errorMessage, supervisorFeed]);

  // Handle user scroll in terminal to detect if autoscroll should pause
  const handleTerminalScroll = () => {
    if (!terminalContainerRef.current) return;
    const { scrollTop, scrollHeight, clientHeight } = terminalContainerRef.current;
    const isAtBottom = scrollHeight - scrollTop - clientHeight < 40;
    if (!isAtBottom && autoScroll) {
      setAutoScroll(false);
    } else if (isAtBottom && !autoScroll) {
      setAutoScroll(true);
    }
  };

  // Auto-scroll when new logs arrive if enabled
  useEffect(() => {
    if (autoScroll) {
      terminalEndRef.current?.scrollIntoView({ behavior: 'smooth' });
    }
  }, [logs, autoScroll]);

  // Connect to live WebSocket stream
  useEffect(() => {
    let ws: WebSocket | null = null;
    let isCancelled = false;
    let opened = false;
    let fallbackTriggered = false;
    const isReexec = reexecuteCounter > 0;

    setLogs([
      isReexec
        ? `[INFO] [Vellum WS] Connecting to live re-execution stream for plan: ${planId}...`
        : `[INFO] [Vellum WS] Connecting to live execution stream for plan: ${planId}...`
    ]);
    setExecuting(true);
    setErrorMessage(null);

    const triggerRestFallback = (reason?: string) => {
      if (fallbackTriggered || isCancelled || opened) return;
      fallbackTriggered = true;

      console.warn('WS connection failed, executing via REST fallback:', reason);
      setLogs((prev) => [
        ...prev,
        `[WARN] [Vellum WS] WebSocket connection unavailable. Executing via REST API fallback...`,
      ]);

      const execAction = api.executePlan(planId);
      execAction
        .then((res) => {
          if (isCancelled) return;
          const tfOut = res.terraform_output;
          if (tfOut) {
            setLogs((prev) => [...prev, tfOut]);
          }
          setLogs((prev) => [
            ...prev,
            `[INFO] [Vellum Engine] Execution finished. Duration: ${res.execution_time_seconds}s`,
          ]);
          setExecutionResult(res);
          if (res.success) {
            setErrorMessage(null);
          } else {
            setErrorMessage(res.error_message || 'Execution failed');
          }
          setExecuting(false);
          runVerification();
        })
        .catch((e) => {
          if (isCancelled) return;
          if (e.message?.includes('already currently executing') || e.message?.includes('409')) {
            // Execution is already active on the server, attach silently
            return;
          }
          setLogs((prev) => [...prev, `[ERROR] [REST Fallback Error]: ${e.message}`]);
          setErrorMessage(e.message);
          setExecuting(false);
        });
    };

    try {
      const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
      const queryParam = isReexec ? '?reexecute=true' : '';
      const wsUrl = `${protocol}//${window.location.host}/ws/execution/${planId}${queryParam}`;
      ws = new WebSocket(wsUrl);

      ws.onopen = () => {
        if (isCancelled) return;
        opened = true;
        setLogs((prev) => [
          ...prev,
          `[INFO] [Vellum Engine] Connected to execution channel. Pipeline initialized.`
        ]);
      };

      ws.onmessage = (event) => {
        if (isCancelled) return;
        const msg = event.data;
        if (msg.startsWith('__HEAL__')) {
          const healStr = msg.replace('__HEAL__', '');
          try {
            const evt = JSON.parse(healStr);
            if (evt.event === 'heal_detected') {
              setCurrentDetectedError({
                signature: evt.signature,
                error_class: evt.error_class,
                message: evt.message || '',
                is_unfixable: evt.remediation_class === 'halted',
                remediation_class: evt.remediation_class || 'auto',
                diagnosis: evt.diagnosis,
              });
              setCurrentAttemptNumber(evt.attempt || 1);
            } else if (evt.event === 'heal_halted') {
              setCurrentDetectedError((prev) => ({
                signature: evt.signature || prev?.signature || 'Error',
                error_class: evt.error_class || prev?.error_class || 'runtime',
                message: evt.diagnosis || 'Execution halted',
                is_unfixable: true,
                remediation_class: 'halted',
                diagnosis: evt.diagnosis,
              }));
            }
            api.getExecutionHeals(planId).then((heals) => {
              setHealingAttempts(heals);
              if (heals.length > 0) {
                const latest = heals[heals.length - 1];
                setExpandedDiffs((prev) => ({ ...prev, [latest.id]: true }));
              }
            }).catch(() => {});
          } catch (e) {
            console.error('Failed to parse heal event', e);
          }
        } else if (msg.startsWith('__COMPLETED__')) {
          const dataStr = msg.replace('__COMPLETED__', '');
          try {
            const res = JSON.parse(dataStr);
            setExecutionResult(res);
            if (res.success) {
              setErrorMessage(null);
            } else {
              setErrorMessage(res.error_message || 'Execution failed');
            }
          } catch {
            // fallback
          }
          setExecuting(false);
          runVerification();
          api.getExecutionHeals(planId).then(setHealingAttempts).catch(() => {});
        } else if (msg.startsWith('__ERROR__')) {
          const err = msg.replace('__ERROR__', '');
          setLogs((prev) => [...prev, `[ERROR] [Execution Error]: ${err}`]);
          setErrorMessage(err);
          setExecuting(false);
          api.getExecutionHeals(planId).then(setHealingAttempts).catch(() => {});
        } else {
          setLogs((prev) => [...prev, msg]);
        }
      };

      ws.onerror = (err) => {
        if (isCancelled) return;
        if (!opened) {
          triggerRestFallback('WebSocket onerror triggered before connection open');
        }
      };

      ws.onclose = (event) => {
        if (isCancelled) return;
        if (!opened) {
          triggerRestFallback(`WebSocket closed before open (code ${event.code})`);
        }
      };
    } catch (e: any) {
      if (!isCancelled) {
        setLogs((prev) => [...prev, `[ERROR] [Connection Exception]: ${e.message}`]);
        triggerRestFallback(e.message);
      }
    }

    return () => {
      isCancelled = true;
      if (ws) {
        ws.onopen = null;
        ws.onmessage = null;
        ws.onerror = null;
        ws.onclose = null;
        ws.close();
      }
    };
  }, [planId, reexecuteCounter]);

  // Initial fetch for heals and errors
  useEffect(() => {
    api.getExecutionHeals(planId).then((heals) => {
      setHealingAttempts(heals);
      if (heals.length > 0) {
        const latest = heals[heals.length - 1];
        setExpandedDiffs((prev) => ({ ...prev, [latest.id]: true }));
        setCurrentAttemptNumber(latest.attempt_number);
      }
    }).catch(() => {});

    api.getExecutionErrors(planId).then((errs) => {
      if (errs && errs.length > 0) {
        setCurrentDetectedError(errs[0]);
      }
    }).catch(() => {});
  }, [planId, reexecuteCounter]);

  const handleApproveHeal = async (attemptId: number, attemptNumber: number) => {
    setApprovingHealId(attemptId);
    try {
      toast({
        title: 'Approving Heal Fix',
        description: `Applying proposed fix for attempt #${attemptNumber}...`,
        type: 'info',
      });
      const res = await api.approveHeal(planId, attemptNumber);
      toast({
        title: 'Fix Applied',
        description: 'Approved fix applied. Re-executing plan...',
        type: 'success',
      });
      if (res.execution_result) {
        setExecutionResult(res.execution_result);
        if (res.execution_result.success) {
          setErrorMessage(null);
        }
      }
      const updatedHeals = await api.getExecutionHeals(planId);
      setHealingAttempts(updatedHeals);
    } catch (e: any) {
      toast({
        title: 'Approval Failed',
        description: e.message,
        type: 'crit',
      });
    } finally {
      setApprovingHealId(null);
    }
  };

  const handleRejectHeal = async (attemptId: number, attemptNumber: number) => {
    setRejectingHealId(attemptId);
    try {
      await api.rejectHeal(planId, attemptNumber);
      toast({
        title: 'Fix Rejected',
        description: 'Heal proposal rejected. Execution stopped cleanly.',
        type: 'warn',
      });
      const updatedHeals = await api.getExecutionHeals(planId);
      setHealingAttempts(updatedHeals);
    } catch (e: any) {
      toast({
        title: 'Reject Failed',
        description: e.message,
        type: 'crit',
      });
    } finally {
      setRejectingHealId(null);
    }
  };


  const runVerification = async () => {
    setVerifying(true);
    try {
      setLogs((prev) => [...prev, `[INFO] [Verification] Auditing state against ${targetLabel}...`]);
      const report = await api.verifyPlan(planId);
      setVerificationResult(report);
      const auditLabel = report.audited_target_label || targetLabel;
      if (report.status === 'incident') {
        setLogs((prev) => [
          ...prev,
          `[CRIT] [Verification Incident]: ${report.error_message || 'Verification halted due to target mismatch.'}`,
        ]);
        toast({
          title: 'Verification Halted',
          description: report.error_message || 'Target mismatch incident detected.',
          type: 'crit',
        });
      } else {
        setLogs((prev) => [
          ...prev,
          `[INFO] [Verification] State audit completed against ${auditLabel}. Resources verified: ${report.resources_verified}. Drift detected: ${report.drift_detected}`,
        ]);
      }
    } catch (e: any) {
      setLogs((prev) => [...prev, `[WARN] [Verification Notice]: ${e.message}`]);
    } finally {
      setVerifying(false);
    }
  };

  const handleCopyLogs = () => {
    navigator.clipboard.writeText(logs.join('\n'));
    toast({
      title: 'Copied',
      description: 'Terminal log copied to clipboard.',
      type: 'success',
    });
  };

  const handleDownloadLogs = () => {
    const blob = new Blob([logs.join('\n')], { type: 'text/plain;charset=utf-8' });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = `vellum-execution-${planId}.log`;
    document.body.appendChild(a);
    a.click();
    a.remove();
    URL.revokeObjectURL(url);
    toast({
      title: 'Downloaded',
      description: `Saved vellum-execution-${planId}.log`,
      type: 'success',
    });
  };

  const handleConfirmRollback = async () => {
    if (rollbackInput.trim().toUpperCase() !== 'DESTROY') {
      toast({
        title: 'Confirmation Mismatch',
        description: 'Type "DESTROY" in all caps to proceed.',
        type: 'crit',
      });
      return;
    }
    setRollingBack(true);
    try {
      setLogs((prev) => [...prev, `[WARN] [Rollback] Initiating rollback destroy against ${targetLabel}...`]);
      const res = await api.rollbackPlan(planId);
      if (res.terraform_output) {
        const outText: string = res.terraform_output;
        setLogs((prev) => [...prev, outText]);
      }
      setLogs((prev) => [...prev, `[INFO] [Rollback] Rollback finished. Success: ${res.success}. Status: ${res.status}`]);
      setShowRollbackModal(false);
      toast({
        title: res.success ? 'Rollback Completed' : 'Rollback Notice',
        description: res.error_message || `Resources processed in ${targetLabel}.`,
        type: res.success ? 'warn' : 'crit',
      });
      if (res.success) {
        setExecutionResult(res);
      }
    } catch (e: any) {
      setLogs((prev) => [...prev, `[CRIT] [Rollback Error]: ${e.message}`]);
      toast({
        title: 'Rollback Failed',
        description: e.message,
        type: 'crit',
      });
    } finally {
      setRollingBack(false);
    }
  };

  const handleReexecute = () => {
    setLogs([`[INFO] [Vellum WS] Connecting to live re-execution stream for plan: ${planId}...`]);
    setExecutionResult(null);
    setVerificationResult(null);
    setErrorMessage(null);
    setExecuting(true);
    setReexecuteCounter((prev) => prev + 1);
    toast({
      title: 'Re-executing Plan',
      description: `Restarting execution pipeline for ${planId}...`,
      type: 'info',
    });
  };

  // Filtered log lines
  const filteredLogs = useMemo(() => {
    if (logFilter === 'ALL') return logs;
    return logs.filter((line) => {
      const upper = line.toUpperCase();
      if (logFilter === 'ERROR') return upper.includes('[ERROR]') || upper.includes('ERROR') || upper.includes('FAIL');
      if (logFilter === 'WARN') return upper.includes('[WARN]') || upper.includes('WARNING');
      if (logFilter === 'INFO') return upper.includes('[INFO]');
      return true;
    });
  }, [logs, logFilter]);

  const getLineClass = (line: string) => {
    const upper = line.toUpperCase();
    if (upper.includes('[ERROR]') || upper.includes('ERROR') || upper.includes('FAIL') || upper.includes('❌')) {
      return 'text-crit';
    }
    if (upper.includes('APPLY COMPLETE') || upper.includes('SUCCEEDED') || upper.includes('✅')) {
      return 'text-ok font-semibold';
    }
    if (upper.includes('[WARN]') || upper.includes('WARNING') || upper.includes('⚠️')) {
      return 'text-warn';
    }
    if (upper.includes('[INFO]')) {
      return 'text-ink-secondary';
    }
    return 'text-ink-primary';
  };

  return (
    <div className="space-y-6">
      {/* Top Header */}
      <div className="flex flex-wrap items-center justify-between gap-4 pb-4 border-b border-line">
        <div className="flex items-center gap-3">
          <Button
            variant="secondary"
            size="sm"
            onClick={onBackToDesigner}
            leftIcon={<ArrowLeft className="h-4 w-4" />}
          >
            Designer
          </Button>

          <div>
            <div className="flex items-center gap-2 flex-wrap">
              <h2 className="text-base font-bold text-ink-primary">Live Execution & Verification</h2>
              <span className="font-mono text-xs font-semibold px-2 py-0.5 rounded bg-brand/10 text-brand border border-brand/20">
                {planId}
              </span>
              <CopyButton value={planId} label="Copy plan ID" className="h-4 w-4 p-0" />
            </div>
            <p className="text-xs text-ink-secondary">
              Real-time pipeline applying Terraform against {targetLabel} with drift audit
            </p>
          </div>
        </div>

        {/* Status Pill, Terminate Button & Re-execute Button */}
        <div className="flex items-center gap-2">
          {executing && (
            <Button
              variant="destructive"
              size="sm"
              loading={terminating}
              onClick={handleHeaderTerminateClick}
              leftIcon={<Square className="h-3.5 w-3.5 fill-current" />}
              className={cn(
                'bg-crit hover:bg-crit/90 text-white font-medium',
                terminateState === 'terminating' && 'animate-pulse bg-warn hover:bg-warn/90 text-ink-primary'
              )}
              title={terminateState === 'terminating' ? 'Click 2: Force Kill (SIGKILL)' : 'Click 1: Graceful Stop (SIGINT)'}
              aria-label={terminateState === 'terminating' ? 'Force Kill execution' : 'Terminate execution'}
            >
              {terminateState === 'terminating' ? '⏹ Force Kill (Click 2)' : '⏹ Terminate'}
            </Button>
          )}

          {!executing && (
            <Button
              variant="secondary"
              size="sm"
              onClick={handleReexecute}
              leftIcon={<RefreshCw className="h-3.5 w-3.5" />}
            >
              Re-execute Plan
            </Button>
          )}

          {executing ? (
            terminateState === 'terminating' ? (
              <Chip variant="warn" icon={<Loader2 className="h-3.5 w-3.5 animate-spin" />}>
                TERMINATING
              </Chip>
            ) : terminateState === 'terminated_reconciling' ? (
              <Chip variant="crit" icon={<Loader2 className="h-3.5 w-3.5 animate-spin" />}>
                TERMINATED/RECONCILING
              </Chip>
            ) : (
              <Chip variant="brand" icon={<Loader2 className="h-3.5 w-3.5 animate-spin" />}>
                Applying Infrastructure
              </Chip>
            )
          ) : executionResult?.success ? (
            <Chip variant="ok" icon={<CheckCircle2 className="h-3.5 w-3.5" />}>
              Execution Succeeded
            </Chip>
          ) : (
            <Chip variant="crit" icon={<AlertCircle className="h-3.5 w-3.5" />}>
              {terminateState === 'terminated_reconciling' ? 'TERMINATED' : 'Execution Failed'}
            </Chip>
          )}
        </div>
      </div>

      {/* Horizontal Stage Stepper */}
      <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-6 gap-2.5">
        {stages.map((stage) => {
          return (
            <div
              key={stage.id}
              className={cn(
                'p-3 rounded-xl border text-xs transition-all flex flex-col justify-between space-y-1',
                stage.status === 'done' && 'bg-ok/10 border-ok/30 text-ok',
                stage.status === 'active' && 'bg-brand/12 border-brand/40 text-brand animate-pulse',
                stage.status === 'failed' && 'bg-crit/10 border-crit/30 text-crit',
                stage.status === 'pending' && 'bg-surface/50 border-line text-ink-tertiary'
              )}
            >
              <div className="flex items-center justify-between">
                <span className="font-mono text-[10px] uppercase tracking-wider font-semibold">
                  Stage 0{stage.id}
                </span>
                {stage.status === 'done' && <Check className="h-3.5 w-3.5" />}
                {stage.status === 'active' && <Loader2 className="h-3.5 w-3.5 animate-spin" />}
                {stage.status === 'failed' && <AlertTriangle className="h-3.5 w-3.5" />}
              </div>
              <div className="font-semibold text-ink-primary">{stage.name}</div>
              <div className="text-[10px] text-ink-secondary truncate">{stage.detail}</div>
            </div>
          );
        })}
      </div>

      {/* Implementation Plan Execution Stepper (F7: infra -> config -> content -> verify -> handoff) */}
      {implementationSteps.length > 0 && (
        <div className="rounded-xl border border-line bg-surface p-3 space-y-2.5 shadow-sm">
          <div className="flex items-center justify-between">
            <div className="flex items-center gap-2">
              <ListChecks className="h-4 w-4 text-brand" />
              <span className="text-xs font-semibold text-ink-primary">Live Implementation Trajectory</span>
              <span className="text-[10px] font-mono px-1.5 py-0.5 rounded bg-brand/10 text-brand font-medium border border-brand/20">
                5 Ordered Steps
              </span>
            </div>
            <span className="text-[11px] text-ink-secondary">
              {executing
                ? 'Applying infrastructure & configuration in sequence...'
                : verifying
                ? 'Executing 100% per-resource functional verification...'
                : executionResult?.success
                ? 'All implementation steps succeeded & verified'
                : 'Execution halted at indicated step'}
            </span>
          </div>

          <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-5 gap-2">
            {implementationSteps.map((step: any) => (
              <div
                key={step.step_number}
                className={cn(
                  'p-2.5 rounded-xl border text-xs transition-all flex flex-col justify-between space-y-1',
                  step.status === 'done' && 'bg-ok/10 border-ok/30 text-ok',
                  step.status === 'active' && 'bg-brand/12 border-brand/40 text-brand animate-pulse',
                  step.status === 'failed' && 'bg-crit/10 border-crit/30 text-crit ring-1 ring-crit/40',
                  step.status === 'pending' && 'bg-surface/50 border-line text-ink-tertiary'
                )}
              >
                <div className="flex items-center justify-between">
                  <span className="font-mono text-[9px] uppercase tracking-wider font-semibold">
                    Step 0{step.step_number} • {step.phase}
                  </span>
                  {step.status === 'done' && <Check className="h-3.5 w-3.5" />}
                  {step.status === 'active' && <Loader2 className="h-3.5 w-3.5 animate-spin" />}
                  {step.status === 'failed' && <AlertTriangle className="h-3.5 w-3.5" />}
                </div>
                <div className="font-semibold text-ink-primary truncate" title={step.name}>
                  {step.name}
                </div>
                <div className="text-[10px] text-ink-secondary truncate" title={step.description}>
                  {step.description}
                </div>
                {step.status === 'failed' && step.agentDecision && (
                  <div
                    className="mt-1 p-1 rounded bg-crit/15 border border-crit/30 text-[9px] text-crit font-medium truncate"
                    title={step.agentDecision}
                  >
                    Agent: {step.agentDecision}
                  </div>
                )}
              </div>
            ))}
          </div>
        </div>
      )}

      {/* M-14: Self-Healing Engine Banner Card */}
      {(currentDetectedError || healingAttempts.length > 0) && (
        <div className="rounded-xl border border-line bg-surface p-4 space-y-4 shadow-sm">
          {/* Header with Signature, Class Chip, Attempt Indicator */}
          <div className="flex flex-wrap items-center justify-between gap-3 pb-3 border-b border-line">
            <div className="flex items-center gap-2.5">
              <div
                className={cn(
                  'p-2 rounded-lg',
                  (currentDetectedError?.remediation_class === 'halted' ||
                    healingAttempts[healingAttempts.length - 1]?.status === 'halted')
                    ? 'bg-crit/10 text-crit'
                    : (currentDetectedError?.remediation_class === 'approve' ||
                        healingAttempts[healingAttempts.length - 1]?.status === 'awaiting_approval')
                    ? 'bg-warn/10 text-warn'
                    : 'bg-ok/10 text-ok'
                )}
              >
                <Wrench className="h-4 w-4" />
              </div>
              <div>
                <div className="flex items-center gap-2 flex-wrap">
                  <span className="text-xs font-bold text-ink-primary">Self-Healing Execution Engine</span>
                  <span className="font-mono text-[11px] font-semibold px-2 py-0.5 rounded bg-base text-ink-primary border border-line">
                    {currentDetectedError?.signature ||
                      healingAttempts[healingAttempts.length - 1]?.error_signature ||
                      'Error Detected'}
                  </span>
                </div>
                <p className="text-[11px] text-ink-secondary mt-0.5">
                  Deterministic error taxonomy classification and auto-remediation pipeline
                </p>
              </div>
            </div>

            <div className="flex items-center gap-2">
              {/* Class Chip: AUTO / APPROVE / HALTED */}
              {(() => {
                const latest = healingAttempts[healingAttempts.length - 1];
                const remClass = currentDetectedError?.remediation_class || latest?.remediation_class || 'auto';
                if (remClass === 'halted' || currentDetectedError?.is_unfixable || latest?.status === 'halted') {
                  return <Chip variant="crit">HALTED</Chip>;
                }
                if (remClass === 'approve' || latest?.status === 'awaiting_approval') {
                  return <Chip variant="warn">APPROVE</Chip>;
                }
                return <Chip variant="ok">AUTO</Chip>;
              })()}

              {/* Attempt x/3 Indicator */}
              <span className="text-xs font-mono font-semibold px-2.5 py-1 rounded-md bg-elevated text-ink-primary border border-line flex items-center gap-1.5">
                <History className="h-3 w-3 text-ink-tertiary" />
                Attempt {healingAttempts.length > 0 ? healingAttempts[healingAttempts.length - 1].attempt_number : currentAttemptNumber} / 3
              </span>
            </div>
          </div>

          {/* Diagnosis or Description */}
          <div className="text-xs text-ink-primary leading-relaxed bg-base p-3 rounded-lg border border-line/60">
            <span className="font-semibold text-ink-secondary">Diagnosis: </span>
            {currentDetectedError?.diagnosis ||
              healingAttempts[healingAttempts.length - 1]?.reasoning ||
              currentDetectedError?.message ||
              errorMessage ||
              'Error detected during execution. Remediation evaluated.'}
          </div>

          {/* Policy Action Buttons */}
          <div className="flex flex-wrap items-center justify-between gap-3 pt-1">
            {(() => {
              const latest = healingAttempts[healingAttempts.length - 1];
              const isHalted =
                currentDetectedError?.remediation_class === 'halted' ||
                currentDetectedError?.is_unfixable ||
                latest?.status === 'halted';
              const isAwaitingApproval = latest?.status === 'awaiting_approval';
              const isAutoFixed =
                latest?.is_auto_applied ||
                latest?.status === 'applied' ||
                (executionResult?.success && healingAttempts.length > 0);

              if (isHalted) {
                return (
                  <div className="w-full p-2.5 rounded-lg bg-crit/10 border border-crit/20 text-crit text-xs flex items-center justify-between gap-2">
                    <div className="flex items-center gap-2">
                      <AlertCircle className="h-4 w-4 shrink-0" />
                      <span className="font-semibold">
                        Halted — human action required: {currentDetectedError?.diagnosis || latest?.reasoning || 'IAM credentials or quota decision needed.'}
                      </span>
                    </div>
                    <CopyButton
                      value={currentDetectedError?.diagnosis || latest?.reasoning || 'Halted'}
                      label="Copy diagnosis"
                    />
                  </div>
                );
              }

              if (isAwaitingApproval && latest) {
                return (
                  <div className="w-full flex flex-wrap items-center justify-between gap-3 p-2.5 rounded-lg bg-warn/10 border border-warn/20">
                    <div className="flex items-center gap-2 text-xs text-warn font-semibold">
                      <AlertTriangle className="h-4 w-4 shrink-0" />
                      <span>Proposal ready for review. Verify diff below and select action:</span>
                    </div>
                    <div className="flex items-center gap-2">
                      <Button
                        variant="primary"
                        size="sm"
                        loading={approvingHealId === latest.id}
                        onClick={() => handleApproveHeal(latest.id, latest.attempt_number)}
                        leftIcon={<Check className="h-3.5 w-3.5" />}
                        className="bg-ok hover:bg-ok/90 text-white"
                      >
                        Approve Fix
                      </Button>
                      <Button
                        variant="secondary"
                        size="sm"
                        loading={rejectingHealId === latest.id}
                        onClick={() => handleRejectHeal(latest.id, latest.attempt_number)}
                        leftIcon={<X className="h-3.5 w-3.5" />}
                      >
                        Reject
                      </Button>
                    </div>
                  </div>
                );
              }

              if (isAutoFixed) {
                return (
                  <div className="flex items-center gap-2 text-xs font-semibold text-ok bg-ok/10 px-3 py-1.5 rounded-lg border border-ok/20">
                    <CheckCircle2 className="h-4 w-4" />
                    <span>Auto-fixed ✓ (Deterministic playbook successfully healed error without manual intervention)</span>
                  </div>
                );
              }

              return null;
            })()}
          </div>
        </div>
      )}

      {/* Healing Attempts Timeline with Before/After Diff Viewer */}
      {healingAttempts.length > 0 && (
        <div className="rounded-xl border border-line bg-surface p-4 space-y-3">
          <div className="flex items-center justify-between pb-2 border-b border-line">
            <div className="flex items-center gap-2">
              <GitCompare className="h-4 w-4 text-brand" />
              <h4 className="text-xs font-bold text-ink-primary">
                Healing Attempt Timeline ({healingAttempts.length} attempt{healingAttempts.length > 1 ? 's' : ''})
              </h4>
            </div>
            <span className="text-[11px] text-ink-tertiary">M-14 Self-Healing Audit Trail</span>
          </div>

          <div className="space-y-3 pt-1">
            {healingAttempts.map((attempt) => {
              const isExpanded = expandedDiffs[attempt.id] ?? false;
              return (
                <div key={attempt.id} className="p-3.5 rounded-lg bg-base border border-line space-y-3 text-xs">
                  <div className="flex flex-wrap items-center justify-between gap-2">
                    <div className="flex items-center gap-2 flex-wrap">
                      <span className="font-mono font-bold text-ink-primary text-xs">
                        Attempt #{attempt.attempt_number}
                      </span>
                      <span className="font-mono text-[11px] px-2 py-0.5 rounded bg-surface border border-line text-ink-secondary">
                        {attempt.error_signature}
                      </span>
                      <Chip
                        variant={
                          attempt.status === 'applied' || attempt.status === 'approved'
                            ? 'ok'
                            : attempt.status === 'awaiting_approval'
                            ? 'warn'
                            : attempt.status === 'halted' || attempt.status === 'rejected'
                            ? 'crit'
                            : 'brand'
                        }
                      >
                        {attempt.status.toUpperCase()}
                      </Chip>
                      {attempt.confidence !== undefined && (
                        <span className="text-[10px] font-mono font-semibold px-1.5 py-0.5 rounded bg-brand/10 text-brand">
                          {Math.round(attempt.confidence * 100)}% Confidence
                        </span>
                      )}
                      <span className="text-[10px] font-mono text-ink-tertiary">
                        Fix: {attempt.fix_type}
                      </span>
                    </div>

                    <div className="flex items-center gap-2">
                      {attempt.status === 'awaiting_approval' && (
                        <div className="flex items-center gap-1.5">
                          <Button
                            variant="primary"
                            size="sm"
                            loading={approvingHealId === attempt.id}
                            onClick={() => handleApproveHeal(attempt.id, attempt.attempt_number)}
                            className="h-6 text-[11px] px-2 bg-ok hover:bg-ok/90 text-white"
                            leftIcon={<Check className="h-3 w-3" />}
                          >
                            Approve
                          </Button>
                          <Button
                            variant="secondary"
                            size="sm"
                            loading={rejectingHealId === attempt.id}
                            onClick={() => handleRejectHeal(attempt.id, attempt.attempt_number)}
                            className="h-6 text-[11px] px-2"
                            leftIcon={<X className="h-3 w-3" />}
                          >
                            Reject
                          </Button>
                        </div>
                      )}
                      {attempt.diff && (
                        <button
                          type="button"
                          onClick={() => setExpandedDiffs((prev) => ({ ...prev, [attempt.id]: !isExpanded }))}
                          className="flex items-center gap-1 text-[11px] text-ink-secondary hover:text-ink-primary font-medium cursor-pointer"
                        >
                          <span>{isExpanded ? 'Hide Diff' : 'View Diff'}</span>
                          {isExpanded ? <ChevronUp className="h-3.5 w-3.5" /> : <ChevronDown className="h-3.5 w-3.5" />}
                        </button>
                      )}
                    </div>
                  </div>

                  {/* Root cause and reasoning */}
                  <div className="space-y-1 text-[11px] text-ink-secondary">
                    <div>
                      <strong className="text-ink-primary">Root Cause:</strong> {attempt.root_cause || attempt.error_message}
                    </div>
                    {attempt.reasoning && (
                      <div>
                        <strong className="text-ink-primary">Reasoning:</strong> {attempt.reasoning}
                      </div>
                    )}
                  </div>

                  {/* Before / After Diff Viewer */}
                  {attempt.diff && isExpanded && (
                    <div className="p-3 rounded-lg bg-surface border border-line font-mono text-[11px] space-y-2">
                      <div className="flex items-center justify-between text-ink-secondary font-semibold text-[10px] pb-1 border-b border-line">
                        <span>PROPOSED DIFF (BEFORE vs AFTER)</span>
                        <span>{attempt.diff.action || attempt.fix_type}</span>
                      </div>

                      {attempt.diff.changes && attempt.diff.changes.length > 0 ? (
                        <div className="space-y-2">
                          {attempt.diff.changes.map((c: any, ci: number) => (
                            <div key={ci} className="space-y-1">
                              <div className="text-brand font-semibold">{c.resource} ({c.action})</div>
                              {c.before && (
                                <div className="text-crit bg-crit/10 p-1.5 rounded">
                                  - {JSON.stringify(c.before)}
                                </div>
                              )}
                              {c.after && (
                                <div className="text-ok bg-ok/10 p-1.5 rounded">
                                  + {JSON.stringify(c.after)}
                                </div>
                              )}
                              {c.properties && (
                                <div className="text-ok bg-ok/10 p-1.5 rounded">
                                  + {JSON.stringify(c.properties)}
                                </div>
                              )}
                            </div>
                          ))}
                        </div>
                      ) : (
                        <div className="space-y-1 text-ink-primary whitespace-pre-wrap">
                          {attempt.diff.old_cidr && attempt.diff.new_cidr ? (
                            <>
                              <div className="text-crit bg-crit/10 p-1.5 rounded">- CIDR: {attempt.diff.old_cidr}</div>
                              <div className="text-ok bg-ok/10 p-1.5 rounded">+ CIDR: {attempt.diff.new_cidr}</div>
                            </>
                          ) : attempt.diff.old_name && attempt.diff.new_name ? (
                            <>
                              <div className="text-crit bg-crit/10 p-1.5 rounded">- S3 Bucket: {attempt.diff.old_name}</div>
                              <div className="text-ok bg-ok/10 p-1.5 rounded">+ S3 Bucket: {attempt.diff.new_name}</div>
                            </>
                          ) : (
                            <pre className="text-ink-secondary text-[10px] max-h-36 overflow-y-auto">
                              {JSON.stringify(attempt.diff, null, 2)}
                            </pre>
                          )}
                        </div>
                      )}
                    </div>
                  )}
                </div>
              );
            })}
          </div>
        </div>
      )}

      {/* M-18: Timeout & Reconciling Banner Card */}
      {executionResult?.status === 'unknown_reconciling' && (
        <div className="p-4 rounded-xl bg-warn/10 border border-warn/30 flex flex-wrap items-center justify-between gap-4">
          <div className="flex items-center gap-3">
            <AlertTriangle className="h-5 w-5 text-warn shrink-0" />
            <div>
              <div className="text-xs font-bold text-warn">Execution Reconciled (Human Action Required)</div>
              <div className="text-xs text-ink-primary mt-0.5">
                {executionResult.error_message || 'Terraform apply timed out. Child process reaped and state refreshed. Choose remediation action:'}
              </div>
            </div>
          </div>

          <div className="flex items-center gap-2">
            <Button
              variant="outline"
              size="sm"
              onClick={handleReexecute}
              leftIcon={<RotateCcw className="h-3.5 w-3.5" />}
            >
              Retry Apply
            </Button>
            <Button
              variant="outline"
              size="sm"
              onClick={runVerification}
              leftIcon={<ShieldCheck className="h-3.5 w-3.5" />}
            >
              Import & Adopt
            </Button>
            <Button
              variant="destructive"
              size="sm"
              onClick={() => {
                setRollbackInput('');
                setShowRollbackModal(true);
              }}
              leftIcon={<AlertCircle className="h-3.5 w-3.5" />}
            >
              Rollback Resources
            </Button>
          </div>
        </div>
      )}

      {/* Execution Failure Banner with Rollback Affordance (Fallback if no active heal) */}
      {errorMessage && !executionResult?.success && executionResult?.status !== 'unknown_reconciling' && healingAttempts.length === 0 && (
        <div className="p-4 rounded-xl bg-crit/10 border border-crit/30 flex flex-wrap items-center justify-between gap-4">
          <div className="flex items-center gap-3">
            <AlertCircle className="h-5 w-5 text-crit shrink-0" />
            <div>
              <div className="text-xs font-bold text-crit">Execution Failed</div>
              <div className="text-xs text-ink-primary mt-0.5">{errorMessage}</div>
            </div>
          </div>

          <div className="flex items-center gap-2">
            {onViewAudit && (
              <Button variant="ghost" size="sm" onClick={onViewAudit} leftIcon={<ExternalLink className="h-3.5 w-3.5" />}>
                View Audit Entry
              </Button>
            )}
            <Button
              variant="destructive"
              size="sm"
              onClick={() => {
                setRollbackInput('');
                setShowRollbackModal(true);
              }}
              leftIcon={<RotateCcw className="h-3.5 w-3.5" />}
            >
              Rollback Resources
            </Button>
          </div>
        </div>
      )}


      {/* M-19 & M-20 Multi-Tab Switcher */}
      <div className="flex items-center gap-2 border-b border-line pb-2 flex-wrap">
        <button
          type="button"
          onClick={() => setActiveTab('terminal')}
          className={cn(
            'flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-medium transition-colors cursor-pointer',
            activeTab === 'terminal'
              ? 'bg-brand/15 text-brand font-semibold'
              : 'text-ink-secondary hover:text-ink-primary hover:bg-elevated'
          )}
        >
          <Terminal className="h-3.5 w-3.5" />
          <span>Live Terminal</span>
          <span className="font-mono text-[10px] px-1.5 py-0.2 rounded-full bg-base border border-line text-ink-secondary">
            {logs.length}
          </span>
        </button>

        <button
          type="button"
          onClick={() => {
            setActiveTab('trace');
            loadTraces();
          }}
          className={cn(
            'flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-medium transition-colors cursor-pointer',
            activeTab === 'trace'
              ? 'bg-brand/15 text-brand font-semibold'
              : 'text-ink-secondary hover:text-ink-primary hover:bg-elevated'
          )}
        >
          <Activity className="h-3.5 w-3.5" />
          <span>AWS Wire Trace (M-19)</span>
          {(traceStats.total > 0 || (executionResult?.wire_traces_count && executionResult.wire_traces_count > 0)) && (
            <span className="font-mono text-[10px] px-1.5 py-0.2 rounded-full bg-base border border-line text-ink-secondary">
              {traceStats.total || executionResult?.wire_traces_count}
            </span>
          )}
          {traceStats.failed > 0 && (
            <span className="font-mono text-[10px] px-1.5 py-0.2 rounded-full bg-crit/15 border border-crit/30 text-crit font-bold">
              {traceStats.failed} err
            </span>
          )}
        </button>

        <button
          type="button"
          onClick={() => {
            setActiveTab('supervisor');
            loadSupervisor();
          }}
          className={cn(
            'flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-medium transition-colors cursor-pointer',
            activeTab === 'supervisor'
              ? 'bg-brand/15 text-brand font-semibold'
              : 'text-ink-secondary hover:text-ink-primary hover:bg-elevated'
          )}
        >
          <Wrench className="h-3.5 w-3.5" />
          <span>Healing Agent (M-20)</span>
          {supervisorFeed.length > 0 && (
            <span className="font-mono text-[10px] px-1.5 py-0.2 rounded-full bg-base border border-line text-ink-secondary">
              {supervisorFeed.length}
            </span>
          )}
        </button>

        <button
          type="button"
          onClick={() => {
            setActiveTab('three_leg');
            if (!verificationResult) {
              runVerification();
            }
          }}
          className={cn(
            'flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-medium transition-colors cursor-pointer',
            activeTab === 'three_leg'
              ? 'bg-brand/15 text-brand font-semibold'
              : 'text-ink-secondary hover:text-ink-primary hover:bg-elevated'
          )}
        >
          <ShieldCheck className="h-3.5 w-3.5" />
          <span>Three-Leg Audit (M-19)</span>
          {verificationResult?.three_leg ? (
            <Chip
              variant={
                verificationResult.three_leg.overall_status === 'pass'
                  ? 'ok'
                  : verificationResult.three_leg.overall_status === 'orphan_detected'
                  ? 'warn'
                  : 'crit'
              }
              className="text-[10px] px-1.5 py-0"
            >
              {verificationResult.three_leg.overall_status.toUpperCase()}
            </Chip>
          ) : executionResult?.three_leg_status ? (
            <Chip
              variant={
                executionResult.three_leg_status === 'pass'
                  ? 'ok'
                  : executionResult.three_leg_status === 'orphan_detected'
                  ? 'warn'
                  : 'crit'
              }
              className="text-[10px] px-1.5 py-0"
            >
              {executionResult.three_leg_status.toUpperCase()}
            </Chip>
          ) : null}
        </button>

        <button
          type="button"
          onClick={() => setActiveTab('checklist')}
          className={cn(
            'flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-medium transition-colors cursor-pointer',
            activeTab === 'checklist'
              ? 'bg-brand/15 text-brand font-semibold'
              : 'text-ink-secondary hover:text-ink-primary hover:bg-elevated'
          )}
        >
          <ListChecks className="h-3.5 w-3.5" />
          <span>Resource Checklist (F6)</span>
          {executionResult?.resource_checklist && executionResult.resource_checklist.length > 0 && (
            <span className={cn(
              "font-mono text-[10px] px-1.5 py-0.2 rounded-full border",
              executionResult.resource_checklist.every(r => r.functional_green)
                ? "bg-ok/15 text-ok border-ok/30"
                : "bg-crit/15 text-crit border-crit/30"
            )}>
              {executionResult.resource_checklist.filter(r => r.functional_green).length}/{executionResult.resource_checklist.length}
            </span>
          )}
        </button>
      </div>

      {/* Tab 1: Live Terminal Pane */}
      {activeTab === 'terminal' && (
        <div className="rounded-xl bg-base border border-line overflow-hidden shadow-sm">
          {/* Terminal Toolbar */}
          <div className="px-4 py-2.5 bg-surface border-b border-line flex flex-wrap items-center justify-between gap-2 text-xs">
            <div className="flex items-center gap-2">
              <Terminal className="h-3.5 w-3.5 text-brand" />
              <span className="font-semibold text-ink-primary">Live Terminal Output</span>
              <span className="text-[10px] font-mono text-ink-tertiary hidden sm:inline">
                (terraform v1.9.8 {targetLabel})
              </span>
            </div>

            {/* Controls: autoscroll, wrap, filter, copy, download */}
            <div className="flex items-center gap-2 flex-wrap">
              {/* Filter pills */}
              <div className="flex items-center rounded-lg bg-elevated border border-line p-0.5 text-[11px]">
                {(['ALL', 'INFO', 'WARN', 'ERROR'] as const).map((lvl) => (
                  <button
                    key={lvl}
                    type="button"
                    onClick={() => setLogFilter(lvl)}
                    className={cn(
                      'px-2 py-0.5 rounded text-xs transition-colors cursor-pointer',
                      logFilter === lvl
                        ? 'bg-brand/20 text-brand font-semibold'
                        : 'text-ink-secondary hover:text-ink-primary'
                    )}
                  >
                    {lvl}
                  </button>
                ))}
              </div>

              <Button
                variant="outline"
                size="sm"
                onClick={() => setAutoScroll(!autoScroll)}
                className="text-[11px] h-7"
              >
                Autoscroll: {autoScroll ? 'ON' : 'OFF'}
              </Button>

              <Button
                variant="outline"
                size="sm"
                onClick={() => setWrapText(!wrapText)}
                className="text-[11px] h-7"
              >
                Wrap: {wrapText ? 'ON' : 'OFF'}
              </Button>

              <Button
                variant="secondary"
                size="sm"
                onClick={handleCopyLogs}
                className="text-[11px] h-7"
                leftIcon={<Copy className="h-3 w-3" />}
              >
                Copy
              </Button>

              <Button
                variant="secondary"
                size="sm"
                onClick={handleDownloadLogs}
                className="text-[11px] h-7"
                leftIcon={<Download className="h-3 w-3" />}
              >
                .log
              </Button>
            </div>
          </div>

          {/* Terminal Body */}
          <div
            ref={terminalContainerRef}
            onScroll={handleTerminalScroll}
            role="log"
            aria-live="polite"
            className={cn(
              'p-4 font-mono text-xs max-h-96 min-h-[220px] overflow-y-auto leading-relaxed select-text',
              wrapText ? 'whitespace-pre-wrap break-all' : 'whitespace-pre overflow-x-auto'
            )}
          >
            {filteredLogs.map((line, idx) => (
              <div key={idx} className={getLineClass(line)}>
                {line}
              </div>
            ))}
            <div ref={terminalEndRef} />
          </div>
        </div>
      )}

      {/* Tab 2: AWS Wire Trace (M-19) */}
      {activeTab === 'trace' && (
        <div className="rounded-xl bg-surface border border-line overflow-hidden shadow-sm space-y-4 p-4">
          {/* Wire Trace Toolbar */}
          <div className="flex flex-wrap items-center justify-between gap-3 pb-3 border-b border-line text-xs">
            <div className="flex items-center gap-3 flex-wrap">
              <div className="flex items-center gap-2">
                <Activity className="h-4 w-4 text-brand" />
                <span className="font-bold text-ink-primary">AWS API Wire Traces</span>
              </div>
              <div className="flex items-center gap-1.5 font-mono text-[11px]">
                <span className="px-2 py-0.5 rounded bg-elevated border border-line text-ink-primary font-semibold">
                  {traceStats.total} Calls
                </span>
                {traceStats.failed > 0 && (
                  <span className="px-2 py-0.5 rounded bg-crit/15 border border-crit/30 text-crit font-bold">
                    {traceStats.failed} Failed
                  </span>
                )}
                {traceStats.confirmed > 0 && (
                  <span className="px-2 py-0.5 rounded bg-ok/15 border border-ok/30 text-ok font-semibold">
                    {traceStats.confirmed} CloudTrail Verified
                  </span>
                )}
                <span className="px-2 py-0.5 rounded bg-base text-ink-tertiary">
                  S3: {traceStats.s3Count} • EC2: {traceStats.ec2Count}
                </span>
              </div>
            </div>

            <div className="flex items-center gap-2 flex-wrap">
              {/* Filter Pills */}
              <div className="flex items-center rounded-lg bg-elevated border border-line p-0.5 text-[11px]">
                {(['ALL', 'FAILED', 'S3', 'EC2', 'TERRAFORM'] as const).map((flt) => (
                  <button
                    key={flt}
                    type="button"
                    onClick={() => setTraceFilter(flt)}
                    className={cn(
                      'px-2 py-0.5 rounded text-xs transition-colors cursor-pointer',
                      traceFilter === flt
                        ? 'bg-brand/20 text-brand font-semibold'
                        : 'text-ink-secondary hover:text-ink-primary'
                    )}
                  >
                    {flt}
                  </button>
                ))}
              </div>

              <Button
                variant="secondary"
                size="sm"
                onClick={loadTraces}
                loading={tracesLoading}
                leftIcon={<RefreshCw className="h-3 w-3" />}
                className="text-[11px] h-7"
              >
                Refresh
              </Button>

              <Button
                variant="outline"
                size="sm"
                onClick={handleExportTraces}
                loading={exportingTrace}
                leftIcon={<FileJson className="h-3 w-3 text-brand" />}
                className="text-[11px] h-7"
              >
                Export JSON (SHA-256)
              </Button>
            </div>
          </div>

          {/* Wire Trace Table */}
          {filteredTraces.length === 0 ? (
            <div className="p-8 text-center text-xs text-ink-tertiary space-y-2">
              <Activity className="h-8 w-8 mx-auto text-ink-tertiary/50" />
              <p>No wire trace records found matching filter ({traceFilter}).</p>
              {executing && <p className="text-[11px] text-brand">Tracing Boto3 and Terraform API calls live...</p>}
            </div>
          ) : (
            <div className="overflow-x-auto border border-line rounded-lg bg-base">
              <table className="w-full text-left font-mono text-[11px]">
                <thead className="bg-surface text-ink-secondary uppercase text-[10px] tracking-wider border-b border-line">
                  <tr>
                    <th className="py-2 px-3">#</th>
                    <th className="py-2 px-3">Time</th>
                    <th className="py-2 px-3">Source</th>
                    <th className="py-2 px-3">Operation</th>
                    <th className="py-2 px-3">Status</th>
                    <th className="py-2 px-3">Request ID</th>
                    <th className="py-2 px-3">Latency</th>
                    <th className="py-2 px-3">CloudTrail</th>
                    <th className="py-2 px-3 text-right">Details</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-line">
                  {filteredTraces.map((trace) => {
                    const isError = trace.http_status >= 400 || Boolean(trace.error_code);
                    return (
                      <tr
                        key={trace.seq}
                        className={cn(
                          'hover:bg-elevated/50 transition-colors cursor-pointer',
                          isError && 'bg-crit/5'
                        )}
                        onClick={() => setSelectedTrace(trace)}
                      >
                        <td className="py-2 px-3 text-ink-tertiary">{trace.seq}</td>
                        <td className="py-2 px-3 text-ink-secondary">
                          {trace.ts ? trace.ts.substring(11, 19) : '-'}
                        </td>
                        <td className="py-2 px-3">
                          <span
                            className={cn(
                              'px-1.5 py-0.5 rounded text-[10px] font-semibold',
                              trace.source === 'terraform'
                                ? 'bg-brand/10 text-brand'
                                : 'bg-elevated text-ink-primary border border-line'
                            )}
                          >
                            {trace.source}
                          </span>
                        </td>
                        <td className="py-2 px-3 text-ink-primary font-semibold">
                          <span className="text-brand">{trace.service}</span>:{trace.operation}
                          {trace.error_code && (
                            <div className="text-crit text-[10px] font-normal truncate max-w-xs">
                              {trace.error_code}
                            </div>
                          )}
                        </td>
                        <td className="py-2 px-3">
                          <span
                            className={cn(
                              'px-1.5 py-0.5 rounded font-bold',
                              isError ? 'bg-crit/15 text-crit' : 'bg-ok/15 text-ok'
                            )}
                          >
                            {trace.http_status}
                          </span>
                        </td>
                        <td className="py-2 px-3 text-ink-secondary truncate max-w-[140px]">
                          {trace.request_id || '-'}
                        </td>
                        <td className="py-2 px-3 text-ink-secondary">
                          {trace.latency_ms}ms
                        </td>
                        <td className="py-2 px-3">
                          {trace.cloudtrail_confirmed ? (
                            <span className="text-ok font-semibold flex items-center gap-1">
                              <Check className="h-3 w-3" />
                              Confirmed
                            </span>
                          ) : (
                            <span className="text-ink-tertiary">-</span>
                          )}
                        </td>
                        <td className="py-2 px-3 text-right">
                          <button
                            type="button"
                            onClick={(e) => {
                              e.stopPropagation();
                              setSelectedTrace(trace);
                            }}
                            className="text-brand hover:underline text-[10px] font-semibold cursor-pointer"
                          >
                            Inspect
                          </button>
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
          )}
        </div>
      )}

      {/* Tab 3: Healing Agent (M-20 Always-On Supervisor) */}
      {activeTab === 'supervisor' && (
        <div className="rounded-xl bg-surface border border-line overflow-hidden shadow-sm space-y-4 p-4">
          {/* Supervisor Toolbar */}
          <div className="flex flex-wrap items-center justify-between gap-3 pb-3 border-b border-line text-xs">
            <div className="flex items-center gap-3">
              <div className="flex items-center gap-2">
                <Wrench className="h-4 w-4 text-brand" />
                <span className="font-bold text-ink-primary">Always-On Healing Supervisor</span>
              </div>
              <div className="flex items-center gap-1.5">
                <span className="px-2 py-0.5 rounded-full bg-ok/15 text-ok font-semibold text-[11px] flex items-center gap-1">
                  <span className="h-1.5 w-1.5 rounded-full bg-ok animate-pulse" />
                  Streaming Scanner Active
                </span>
                <span className="px-2 py-0.5 rounded bg-elevated border border-line text-ink-secondary font-mono text-[10px]">
                  Stall threshold: 180s
                </span>
              </div>
            </div>

            <Button
              variant="secondary"
              size="sm"
              onClick={loadSupervisor}
              loading={supervisorLoading}
              leftIcon={<RefreshCw className="h-3 w-3" />}
              className="text-[11px] h-7"
            >
              Refresh Feed
            </Button>
          </div>

          {/* Supervisor Events Timeline */}
          {supervisorFeed.length === 0 ? (
            <div className="p-8 text-center text-xs text-ink-tertiary space-y-2">
              <Sparkles className="h-8 w-8 mx-auto text-brand/40 animate-pulse" />
              <p className="font-semibold text-ink-primary">Supervisor is actively scanning execution lines from second 0.</p>
              <p className="text-[11px] text-ink-tertiary">
                Deterministic regex matcher evaluates every output chunk against known failure taxonomies and stall thresholds.
              </p>
            </div>
          ) : (
            <div className="space-y-3">
              {supervisorFeed.map((evt) => {
                const phase = evt.phase.toUpperCase();
                return (
                  <div
                    key={evt.seq}
                    className="p-3.5 rounded-lg bg-base border border-line space-y-2 text-xs"
                  >
                    <div className="flex flex-wrap items-center justify-between gap-2">
                      <div className="flex items-center gap-2 flex-wrap">
                        <span className="font-mono text-[10px] text-ink-tertiary">
                          #{evt.seq} • {evt.timestamp ? evt.timestamp.substring(11, 19) : ''}
                        </span>
                        <Chip
                          variant={
                            phase === 'DETECT'
                              ? 'warn'
                              : phase === 'DECIDE'
                              ? 'brand'
                              : phase === 'ACT' || phase === 'VERIFY' || phase === 'AUDIT'
                              ? 'ok'
                              : 'neutral'
                          }
                          className="font-mono text-[10px]"
                        >
                          {phase}
                        </Chip>
                        {evt.signature && (
                          <span className="font-mono text-[11px] font-semibold px-2 py-0.5 rounded bg-surface border border-line text-ink-primary">
                            {evt.signature}
                          </span>
                        )}
                        {evt.confidence > 0 && (
                          <span className="font-mono text-[10px] px-1.5 py-0.5 rounded bg-brand/10 text-brand font-semibold">
                            {Math.round(evt.confidence * 100)}% Confidence
                          </span>
                        )}
                      </div>

                      {evt.decision && (
                        <span className="font-mono text-[11px] font-bold text-ok bg-ok/10 px-2 py-0.5 rounded border border-ok/20">
                          Decision: {evt.decision}
                        </span>
                      )}
                    </div>

                    {evt.diagnosis && (
                      <div className="text-[11px] text-ink-secondary">
                        <strong className="text-ink-primary">Diagnosis:</strong> {evt.diagnosis}
                      </div>
                    )}

                    {evt.reasoning && (
                      <div className="text-[11px] text-ink-secondary">
                        <strong className="text-ink-primary">Reasoning:</strong> {evt.reasoning}
                      </div>
                    )}

                    <div className="p-2 rounded bg-surface border border-line/60 font-mono text-[11px] text-ink-primary whitespace-pre-wrap">
                      {evt.message}
                    </div>
                  </div>
                );
              })}
            </div>
          )}
        </div>
      )}

      {/* Tab 4: Three-Leg Audit (M-19) */}
      {activeTab === 'three_leg' && (
        <div className="rounded-xl bg-surface border border-line overflow-hidden shadow-sm space-y-4 p-4">
          {/* Header & Verification Trigger */}
          <div className="flex flex-wrap items-center justify-between gap-3 pb-3 border-b border-line text-xs">
            <div className="flex items-center gap-2">
              <ShieldCheck className="h-4 w-4 text-brand" />
              <div>
                <h3 className="font-bold text-ink-primary">Three-Leg Verification Engine (M-19)</h3>
                <p className="text-[11px] text-ink-secondary">
                  Leg 1 (Intent) ⟷ Leg 2 (Wire Trace) ⟷ Leg 3 (Cloud Truth + CloudTrail)
                </p>
              </div>
            </div>

            <Button
              variant="secondary"
              size="sm"
              disabled={verifying}
              onClick={runVerification}
              leftIcon={<RefreshCw className={`h-3.5 w-3.5 ${verifying ? 'animate-spin' : ''}`} />}
              className="text-[11px] h-7"
            >
              Run Three-Leg Audit
            </Button>
          </div>

          {/* Three-Leg Status Banner */}
          {verificationResult?.three_leg ? (
            <div
              className={cn(
                'p-3.5 rounded-lg border text-xs flex flex-wrap items-center justify-between gap-3',
                verificationResult.three_leg.all_legs_agreed
                  ? 'bg-ok/10 border-ok/30 text-ok'
                  : verificationResult.three_leg.orphan_resources_detected || verificationResult.three_leg.zombie_events_detected
                  ? 'bg-warn/10 border-warn/30 text-warn'
                  : 'bg-crit/10 border-crit/30 text-crit'
              )}
            >
              <div className="flex items-center gap-2.5 font-semibold">
                {verificationResult.three_leg.all_legs_agreed ? (
                  <>
                    <CheckCircle2 className="h-4 w-4 shrink-0" />
                    <span>Three-Leg Verification PASSED ✓ (Intent, Wire Traces, and Cloud Truth fully agree)</span>
                  </>
                ) : verificationResult.three_leg.orphan_resources_detected ? (
                  <>
                    <AlertTriangle className="h-4 w-4 shrink-0" />
                    <span>ORPHAN RESOURCES DETECTED: Cloud resources exist that were not tracked by Terraform state</span>
                  </>
                ) : verificationResult.three_leg.zombie_events_detected ? (
                  <>
                    <AlertTriangle className="h-4 w-4 shrink-0" />
                    <span>ZOMBIE AWS EVENTS DETECTED: CloudTrail recorded calls during execution that were not tracked</span>
                  </>
                ) : (
                  <>
                    <AlertCircle className="h-4 w-4 shrink-0" />
                    <span>THREE-LEG DISCREPANCY: Discrepancy detected between Intent, Wire, or Truth</span>
                  </>
                )}
              </div>
              <span className="font-mono text-[11px] px-2 py-0.5 rounded bg-surface border border-line">
                Status: {verificationResult.three_leg.overall_status.toUpperCase()}
              </span>
            </div>
          ) : (
            <div className="p-4 rounded-lg bg-base border border-line text-xs text-ink-secondary flex items-center justify-between">
              <span>Verification report pending. Run audit to reconcile all three legs against {targetLabel}.</span>
              <Button variant="primary" size="sm" onClick={runVerification} loading={verifying}>
                Audit Now
              </Button>
            </div>
          )}

          {/* Three Legs 3-Column Grid */}
          <div className="grid grid-cols-1 md:grid-cols-3 gap-4 text-xs">
            {/* Leg 1: INTENT */}
            <div className="p-4 rounded-lg bg-elevated border border-line space-y-3">
              <div className="flex items-center justify-between border-b border-line pb-2">
                <div>
                  <div className="font-bold text-ink-primary">LEG 1: INTENT</div>
                  <div className="text-[10px] text-ink-secondary">Terraform Plan Diff / IR</div>
                </div>
                <span className="font-mono text-brand font-bold text-xs">
                  {verificationResult?.three_leg?.leg1_intent?.resources_count ??
                    verificationResult?.expected_resources?.length ??
                    0}{' '}
                  Resources
                </span>
              </div>

              <div className="space-y-1.5 font-mono text-[11px]">
                <div className="text-ink-secondary">
                  Provider: <span className="text-ink-primary font-semibold">{targetProvider}</span>
                </div>
                <div className="text-ink-secondary">
                  Environment: <span className="text-ink-primary font-semibold">{targetEnv}</span>
                </div>
              </div>

              <div className="space-y-1">
                <span className="text-[10px] uppercase font-semibold text-ink-tertiary">Desired Resources:</span>
                <ul className="space-y-1 font-mono text-[11px] max-h-36 overflow-y-auto">
                  {(verificationResult?.three_leg?.leg1_intent?.resources || verificationResult?.expected_resources || []).map(
                    (r: string, i: number) => (
                      <li key={i} className="text-ink-primary truncate flex items-center gap-1.5">
                        <span className="h-1.5 w-1.5 rounded-full bg-brand shrink-0" />
                        <span className="truncate">{r}</span>
                      </li>
                    )
                  )}
                </ul>
              </div>
            </div>

            {/* Leg 2: WIRE TRACE */}
            <div className="p-4 rounded-lg bg-elevated border border-line space-y-3">
              <div className="flex items-center justify-between border-b border-line pb-2">
                <div>
                  <div className="font-bold text-ink-primary">LEG 2: WIRE TRACE</div>
                  <div className="text-[10px] text-ink-secondary">Boto3 & TF API Wire Log</div>
                </div>
                <span className="font-mono text-brand font-bold text-xs">
                  {verificationResult?.three_leg?.leg2_wire?.traces_count ?? traceStats.total} Calls
                </span>
              </div>

              <div className="space-y-1.5 font-mono text-[11px]">
                <div className="text-ok">
                  Success (2xx):{' '}
                  <span className="font-semibold">
                    {verificationResult?.three_leg?.leg2_wire?.successful_calls ?? (traceStats.total - traceStats.failed)}
                  </span>
                </div>
                <div className="text-crit">
                  Failed (4xx/5xx):{' '}
                  <span className="font-semibold">
                    {verificationResult?.three_leg?.leg2_wire?.failed_calls ?? traceStats.failed}
                  </span>
                </div>
                <div className="text-ink-secondary">
                  Captured Request IDs:{' '}
                  <span className="text-ink-primary font-semibold">
                    {verificationResult?.three_leg?.leg2_wire?.distinct_request_ids ?? traceStats.total}
                  </span>
                </div>
              </div>

              <div className="space-y-1">
                <span className="text-[10px] uppercase font-semibold text-ink-tertiary">Services Called:</span>
                <div className="flex flex-wrap gap-1">
                  {(verificationResult?.three_leg?.leg2_wire?.services || ['s3', 'ec2']).map(
                    (s: string, i: number) => (
                      <span key={i} className="px-1.5 py-0.5 rounded bg-base text-ink-primary font-mono text-[10px] border border-line">
                        {s.toUpperCase()}
                      </span>
                    )
                  )}
                </div>
              </div>
            </div>

            {/* Leg 3: TRUTH */}
            <div className="p-4 rounded-lg bg-elevated border border-line space-y-3">
              <div className="flex items-center justify-between border-b border-line pb-2">
                <div>
                  <div className="font-bold text-ink-primary">LEG 3: TRUTH</div>
                  <div className="text-[10px] text-ink-secondary">Cloud Read-back + CloudTrail</div>
                </div>
                <span className="font-mono text-ok font-bold text-xs">
                  {verificationResult?.three_leg?.leg3_truth?.live_resources_count ??
                    verificationResult?.found_resources?.length ??
                    0}{' '}
                  Found
                </span>
              </div>

              <div className="space-y-1.5 font-mono text-[11px]">
                <div className="text-ink-secondary">
                  CloudTrail Matched:{' '}
                  <span className="text-ok font-semibold">
                    {verificationResult?.three_leg?.leg3_truth?.cloudtrail_events_matched ?? traceStats.confirmed}
                  </span>
                </div>
                <div className="text-ink-secondary">
                  Zombies Flagged:{' '}
                  <span
                    className={
                      verificationResult?.three_leg?.zombie_events_detected ? 'text-crit font-bold' : 'text-ok font-semibold'
                    }
                  >
                    {verificationResult?.three_leg?.leg3_truth?.zombies_found ?? 0}
                  </span>
                </div>
                <div className="text-ink-secondary">
                  Drift Status:{' '}
                  <span
                    className={
                      verificationResult?.drift_detected ? 'text-crit font-semibold' : 'text-ok font-semibold'
                    }
                  >
                    {verificationResult?.drift_detected ? 'Drift Detected' : 'Clean (No Drift)'}
                  </span>
                </div>
              </div>

              <div className="space-y-1">
                <span className="text-[10px] uppercase font-semibold text-ink-tertiary">Live Verified:</span>
                <ul className="space-y-1 font-mono text-[11px] max-h-36 overflow-y-auto">
                  {(verificationResult?.three_leg?.leg3_truth?.live_resources_found || verificationResult?.found_resources || []).map(
                    (r: string, i: number) => (
                      <li key={i} className="text-ok truncate flex items-center gap-1.5">
                        <Check className="h-3 w-3 shrink-0" />
                        <span className="truncate">{r}</span>
                      </li>
                    )
                  )}
                </ul>
              </div>
            </div>
          </div>
        </div>
      )}

      {/* Tab 5: F6 Resource Verification Checklist */}
      {activeTab === 'checklist' && (
        <div className="p-6 rounded-xl bg-surface border border-line space-y-4">
          <div className="flex flex-wrap items-center justify-between gap-3">
            <div className="flex items-center gap-2">
              <CheckCircle2 className="h-5 w-5 text-brand" />
              <div>
                <h3 className="text-sm font-semibold text-ink-primary">
                  Resource Verification Checklist (F6)
                </h3>
                <p className="text-xs text-ink-secondary">
                  COMPLETED requires 100% of IR resources verified present and functional checks green
                </p>
              </div>
            </div>
            {executionResult?.resource_checklist && executionResult.resource_checklist.length > 0 && (
              <Chip
                variant={executionResult.resource_checklist.every(r => r.functional_green) ? 'ok' : 'crit'}
                className="text-xs"
              >
                {executionResult.resource_checklist.every(r => r.functional_green)
                  ? 'ALL RESOURCES VERIFIED'
                  : 'PARTIAL VERIFICATION FAILURE'}
              </Chip>
            )}
          </div>

          {(!executionResult?.resource_checklist || executionResult.resource_checklist.length === 0) ? (
            <div className="p-4 rounded-lg bg-base border border-line text-xs text-ink-secondary">
              No resource checklist available yet. Checklist populates upon execution completion and per-resource verification.
            </div>
          ) : (
            <div className="divide-y divide-line border border-line rounded-lg overflow-hidden bg-base">
              {executionResult.resource_checklist.map((item, idx) => (
                <div key={idx} className="p-3.5 flex items-start justify-between gap-3 text-xs">
                  <div className="space-y-1">
                    <div className="flex items-center gap-2">
                      <span className="font-semibold text-ink-primary font-mono">{item.name}</span>
                      <span className="px-1.5 py-0.5 rounded text-[10px] bg-elevated text-ink-secondary border border-line font-mono">
                        {item.type}
                      </span>
                    </div>
                    <div className="text-ink-secondary">{item.details}</div>
                    {item.error && (
                      <div className="text-crit font-medium text-[11px] mt-1 flex items-center gap-1">
                        <AlertCircle className="h-3.5 w-3.5 shrink-0" />
                        <span>{item.error}</span>
                      </div>
                    )}
                  </div>
                  <div>
                    {item.functional_green ? (
                      <span className="px-2 py-0.5 rounded-full text-[10px] font-bold bg-ok/15 text-ok border border-ok/30 flex items-center gap-1">
                        <Check className="h-3 w-3" /> VERIFIED
                      </span>
                    ) : (
                      <span className="px-2 py-0.5 rounded-full text-[10px] font-bold bg-crit/15 text-crit border border-crit/30 flex items-center gap-1">
                        <AlertCircle className="h-3 w-3" /> FAILED
                      </span>
                    )}
                  </div>
                </div>
              ))}
            </div>
          )}
        </div>
      )}

      {/* State Verification & Drift Audit Card (Always accessible summary) */}
      {verificationResult && (
        <div className="p-6 rounded-xl bg-surface border border-line space-y-4">
          <div className="flex flex-wrap items-center justify-between gap-3">
            <div className="flex items-center gap-2">
              <ShieldCheck className="h-5 w-5 text-brand" />
              <div>
                <h3 className="text-sm font-semibold text-ink-primary">
                  State Verification & Drift Audit
                </h3>
                <p className="text-xs text-ink-secondary">
                  Audits instantiated AWS resources against desired Universal IR state
                </p>
              </div>
            </div>

            <Button
              variant="secondary"
              size="sm"
              disabled={verifying}
              onClick={runVerification}
              leftIcon={<RefreshCw className={`h-3.5 w-3.5 ${verifying ? 'animate-spin' : ''}`} />}
            >
              Re-verify Drift
            </Button>
          </div>

          {/* Drift Banner */}
          <div
            className={cn(
              'p-3 rounded-lg border text-xs flex items-center justify-between',
              verificationResult.drift_detected
                ? 'bg-crit/10 border-crit/30 text-crit'
                : 'bg-ok/10 border-ok/30 text-ok'
            )}
          >
            <div className="flex items-center gap-2 font-semibold">
              {verificationResult.drift_detected ? (
                <>
                  <AlertTriangle className="h-4 w-4" />
                  <span>Drift Detected: Resources missing or altered in {targetLabel}</span>
                </>
              ) : (
                <>
                  <CheckCircle2 className="h-4 w-4" />
                  <span>No Drift Detected: Cloud state exactly matches Universal IR</span>
                </>
              )}
            </div>
            <span className="font-mono text-[11px]">
              {verificationResult.resources_verified} resources verified
            </span>
          </div>

          {/* 3-column verification table */}
          <div className="grid grid-cols-1 md:grid-cols-3 gap-4 text-xs">
            {/* Expected */}
            <div className="p-3.5 rounded-lg bg-elevated border border-line space-y-2">
              <div className="flex items-center justify-between text-ink-secondary font-semibold">
                <span>Expected Resources</span>
                <span className="font-mono text-ink-primary">
                  {verificationResult.expected_resources?.length || 0}
                </span>
              </div>
              <ul className="space-y-1 font-mono text-[11px] max-h-36 overflow-y-auto">
                {verificationResult.expected_resources?.map((r, i) => (
                  <li key={i} className="text-ink-primary truncate flex items-center gap-1.5">
                    <span className="h-1.5 w-1.5 rounded-full bg-brand shrink-0" />
                    <span className="truncate">{r}</span>
                  </li>
                ))}
              </ul>
            </div>

            {/* Found */}
            <div className="p-3.5 rounded-lg bg-elevated border border-line space-y-2">
              <div className="flex items-center justify-between text-ink-secondary font-semibold">
                <span>Found in {targetLabel}</span>
                <span className="font-mono text-ok">
                  {verificationResult.found_resources?.length || 0}
                </span>
              </div>
              <ul className="space-y-1 font-mono text-[11px] max-h-36 overflow-y-auto">
                {verificationResult.found_resources?.map((r, i) => (
                  <li key={i} className="text-ok truncate flex items-center gap-1.5">
                    <Check className="h-3 w-3 shrink-0" />
                    <span className="truncate">{r}</span>
                  </li>
                ))}
              </ul>
            </div>

            {/* Missing */}
            <div className="p-3.5 rounded-lg bg-elevated border border-line space-y-2">
              <div className="flex items-center justify-between text-ink-secondary font-semibold">
                <span>Missing (Drift)</span>
                <span className="font-mono text-crit">
                  {verificationResult.missing_resources?.length || 0}
                </span>
              </div>
              <ul className="space-y-1 font-mono text-[11px] max-h-36 overflow-y-auto">
                {verificationResult.missing_resources?.length === 0 ? (
                  <li className="text-ink-tertiary italic text-[11px]">None</li>
                ) : (
                  verificationResult.missing_resources?.map((r, i) => (
                    <li key={i} className="text-crit truncate flex items-center gap-1.5">
                      <AlertTriangle className="h-3 w-3 shrink-0" />
                      <span className="truncate">{r}</span>
                    </li>
                  ))
                )}
              </ul>
            </div>
          </div>
        </div>
      )}

      {/* Terminate Process Modal (M-20: Graceful SIGINT vs Force SIGKILL) */}
      <Modal
        isOpen={showTerminateModal}
        onClose={() => !terminating && setShowTerminateModal(false)}
        title="Terminate Execution Process"
        description="Stop active Terraform execution safely (SIGINT) or forcefully (SIGKILL)."
        icon={<AlertOctagon className="h-5 w-5 text-crit" />}
      >
        <div className="space-y-4 text-xs">
          <div className="p-3 rounded-lg bg-base border border-line space-y-2">
            <div className="font-semibold text-ink-primary flex items-center gap-1.5">
              <AlertTriangle className="h-4 w-4 text-warn" />
              Two-Stage Execution Control
            </div>
            <p className="text-ink-secondary leading-relaxed">
              Terraform is currently running against {targetLabel}. Graceful Stop is recommended first to allow Terraform to finish in-flight state writes and release locks.
            </p>
          </div>

          <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
            <div className="p-3.5 rounded-lg border border-line bg-surface space-y-2 flex flex-col justify-between">
              <div>
                <div className="font-semibold text-ink-primary flex items-center gap-1.5">
                  <span className="font-mono text-ok text-[11px] bg-ok/10 px-1.5 py-0.5 rounded border border-ok/20">
                    SIGINT
                  </span>
                  Graceful Stop
                </div>
                <p className="text-[11px] text-ink-secondary mt-1">
                  Requests clean stop. Terraform halts creating new resources, flushes state, and unlocks remote state safely.
                </p>
              </div>
              <Button
                variant="outline"
                size="sm"
                loading={terminating}
                onClick={() => handleTerminate(false)}
                className="w-full mt-2"
              >
                Graceful Stop (SIGINT)
              </Button>
            </div>

            <div className="p-3.5 rounded-lg border border-crit/30 bg-crit/5 space-y-2 flex flex-col justify-between">
              <div>
                <div className="font-semibold text-crit flex items-center gap-1.5">
                  <span className="font-mono text-crit text-[11px] bg-crit/10 px-1.5 py-0.5 rounded border border-crit/20">
                    SIGKILL
                  </span>
                  Force Kill + Reconcile
                </div>
                <p className="text-[11px] text-ink-secondary mt-1">
                  Immediate process kill. Reaps zombie child processes and triggers mandatory state refresh to clear phantom locks.
                </p>
              </div>
              <Button
                variant="destructive"
                size="sm"
                loading={terminating}
                onClick={() => handleTerminate(true)}
                className="w-full mt-2"
              >
                Force Kill (SIGKILL)
              </Button>
            </div>
          </div>

          <div className="flex justify-end pt-2">
            <Button
              variant="secondary"
              size="sm"
              disabled={terminating}
              onClick={() => setShowTerminateModal(false)}
            >
              Cancel
            </Button>
          </div>
        </div>
      </Modal>

      {/* Wire Trace Inspect Modal */}
      <Modal
        isOpen={Boolean(selectedTrace)}
        onClose={() => setSelectedTrace(null)}
        title={`Wire Trace #${selectedTrace?.seq}: ${selectedTrace?.service}:${selectedTrace?.operation}`}
        description={`Captured wire-level API call from ${selectedTrace?.source}`}
        icon={<Activity className="h-5 w-5 text-brand" />}
      >
        {selectedTrace && (
          <div className="space-y-4 text-xs font-mono">
            <div className="grid grid-cols-2 gap-3 p-3 rounded-lg bg-base border border-line">
              <div>
                <span className="text-ink-tertiary">HTTP Status:</span>{' '}
                <span
                  className={
                    selectedTrace.http_status < 400 ? 'text-ok font-bold' : 'text-crit font-bold'
                  }
                >
                  {selectedTrace.http_status}
                </span>
              </div>
              <div>
                <span className="text-ink-tertiary">Latency:</span> {selectedTrace.latency_ms} ms
              </div>
              <div>
                <span className="text-ink-tertiary">Request ID:</span>{' '}
                <span className="truncate">{selectedTrace.request_id || 'N/A'}</span>
              </div>
              <div>
                <span className="text-ink-tertiary">CloudTrail:</span>{' '}
                {selectedTrace.cloudtrail_confirmed ? (
                  <span className="text-ok font-semibold">✓ Confirmed</span>
                ) : (
                  <span className="text-ink-secondary">Unchecked / Simulation</span>
                )}
              </div>
              {selectedTrace.error_code && (
                <div className="col-span-2 text-crit">
                  <span className="text-ink-tertiary">Error Code:</span> {selectedTrace.error_code}
                </div>
              )}
              {selectedTrace.error_message && (
                <div className="col-span-2 text-crit whitespace-pre-wrap">
                  <span className="text-ink-tertiary">Error Message:</span> {selectedTrace.error_message}
                </div>
              )}
            </div>

            <div>
              <div className="flex items-center justify-between pb-1 text-ink-secondary font-semibold text-[11px]">
                <span>Sanitized Parameters (Masked):</span>
                <CopyButton
                  value={JSON.stringify(selectedTrace.params_masked, null, 2)}
                  label="Copy JSON"
                />
              </div>
              <pre className="p-3 rounded-lg bg-elevated border border-line max-h-60 overflow-y-auto text-[11px] text-ink-primary whitespace-pre-wrap">
                {JSON.stringify(selectedTrace.params_masked, null, 2)}
              </pre>
            </div>

            <div className="flex justify-end pt-2">
              <Button variant="secondary" size="sm" onClick={() => setSelectedTrace(null)}>
                Close
              </Button>
            </div>
          </div>
        )}
      </Modal>

      {/* Rollback Type-to-Confirm Modal */}
      <Modal
        isOpen={showRollbackModal}
        onClose={() => setShowRollbackModal(false)}
        title="Confirm Infrastructure Rollback"
        description={`This will destroy all resources created by this plan in ${targetLabel}.`}
        icon={<RotateCcw className="h-5 w-5 text-crit" />}
      >
        <div className="space-y-4">
          <p className="text-xs text-ink-secondary leading-relaxed">
            Rolling back will execute <code className="text-crit bg-base px-1.5 py-0.5 rounded border border-line font-mono">terraform destroy</code> against {targetLabel}.
            To confirm this destructive action, type <strong className="font-mono text-ink-primary bg-base px-2 py-0.5 rounded border border-line">DESTROY</strong> below:
          </p>

          <input
            type="text"
            value={rollbackInput}
            onChange={(e) => setRollbackInput(e.target.value)}
            placeholder='Type "DESTROY"'
            autoFocus
            className="w-full bg-base border border-line rounded-lg px-3 py-2 text-xs font-mono text-ink-primary focus:outline-none focus:ring-2 focus:ring-crit"
          />

          <div className="flex justify-end gap-2 pt-2">
            <Button variant="secondary" size="sm" onClick={() => setShowRollbackModal(false)}>
              Cancel
            </Button>
            <Button
              variant="destructive"
              size="sm"
              loading={rollingBack}
              disabled={rollbackInput.trim().toUpperCase() !== 'DESTROY'}
              onClick={handleConfirmRollback}
            >
              Confirm Rollback
            </Button>
          </div>
        </div>
      </Modal>
    </div>
  );
};
