import React, { useState } from 'react';
import {
  Cloud,
  Database,
  Code,
  ShieldAlert,
  DollarSign,
  Network,
  Layers,
  HardDrive,
  Key,
  Copy,
  Download,
  Edit3,
  CheckCircle2,
  XCircle,
  AlertTriangle,
  ExternalLink,
  RefreshCw,
  FileText,
  Loader2,
  Sparkles,
  Check,
  Eye,
  ListChecks,
} from 'lucide-react';
import { PlanResponse } from '../../types';
import { Tabs } from '../ui/Tabs';
import { Chip } from '../ui/Chip';
import { Button } from '../ui/Button';
import { Modal } from '../ui/Modal';
import { Tooltip } from '../ui/Tooltip';
import { CopyButton } from '../ui/CopyButton';
import { MarkdownRenderer } from '../ui/MarkdownRenderer';
import { useToast } from '../ui/Toast';
import { formatCurrency } from '../../lib/utils';
import { SchemaViewer } from '../PlanPreview/SchemaViewer';
import { api } from '../../services/api';

export interface WorkspacePaneProps {
  plan: PlanResponse | null;
  onApprove: (confirmationText?: string, customTf?: string, customSql?: string) => void;
  onReject: () => void;
  onModify: (modifications: string) => void;
  isProcessing: boolean;
  onReexecute?: () => void;
  onViewExecution?: () => void;
  onViewAudit?: () => void;
  driftDiff?: {
    missing?: string[];
    verified?: number;
    expected?: string[];
    found?: string[];
  } | null;
  requirementsMd?: string;
  onUpdateRequirements?: (newMd: string) => void;
  onSynthesizePlan?: () => void;
}

const RequirementsView: React.FC<{
  requirementsMd: string;
  isEditing: boolean;
  setIsEditing: (val: boolean) => void;
  draft: string;
  setDraft: (val: string) => void;
  onSave?: (newMd: string) => void;
  onSynthesizePlan?: () => void;
  isProcessing?: boolean;
}> = ({
  requirementsMd,
  isEditing,
  setIsEditing,
  draft,
  setDraft,
  onSave,
  onSynthesizePlan,
  isProcessing,
}) => {
  const { toast } = useToast();
  const [viewMode, setViewMode] = useState<'formatted' | 'raw'>('formatted');

  const handleDownload = () => {
    const blob = new Blob([draft || requirementsMd], { type: 'text/markdown;charset=utf-8' });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = 'requirements.md';
    document.body.appendChild(a);
    a.click();
    a.remove();
    URL.revokeObjectURL(url);
    toast({
      title: 'Downloaded',
      description: 'Saved requirements.md to disk.',
      type: 'success',
    });
  };

  const handleSave = () => {
    if (onSave) {
      onSave(draft);
    }
    setIsEditing(false);
  };

  return (
    <div className="h-full flex flex-col bg-surface overflow-hidden">
      {/* Requirements Action Bar */}
      <div className="px-6 py-3.5 border-b border-line bg-surface/90 flex flex-wrap items-center justify-between gap-3 shrink-0">
        <div className="space-y-0.5">
          <div className="flex items-center gap-2">
            <div className="h-6 w-6 rounded-md bg-brand/10 border border-brand/25 flex items-center justify-center text-brand">
              <FileText className="h-3.5 w-3.5" />
            </div>
            <h2 className="text-sm font-semibold text-ink-primary">Architecture Specification (requirements.md)</h2>
            <span className="text-[10px] font-mono px-2 py-0.5 rounded bg-brand/15 text-brand font-medium border border-brand/30">
              Live Document
            </span>
          </div>
          <p className="text-[11px] text-ink-secondary pl-8">
            Continuous architecture specification consolidated from your AI conversation
          </p>
        </div>

        <div className="flex items-center gap-2">
          {isEditing ? (
            <>
              <Button
                variant="secondary"
                size="sm"
                onClick={() => {
                  setDraft(requirementsMd);
                  setIsEditing(false);
                }}
              >
                Cancel
              </Button>
              <Button
                variant="primary"
                size="sm"
                onClick={handleSave}
                leftIcon={<Check className="h-3.5 w-3.5" />}
              >
                Save Specification
              </Button>
            </>
          ) : (
            <>
              <Button
                variant="secondary"
                size="sm"
                onClick={() => setViewMode(viewMode === 'formatted' ? 'raw' : 'formatted')}
                leftIcon={viewMode === 'formatted' ? <Code className="h-3.5 w-3.5" /> : <Eye className="h-3.5 w-3.5" />}
                title={viewMode === 'formatted' ? 'View raw Markdown source' : 'View formatted Markdown'}
              >
                {viewMode === 'formatted' ? 'Raw MD' : 'Formatted'}
              </Button>
              <Button
                variant="secondary"
                size="sm"
                onClick={() => setIsEditing(true)}
                leftIcon={<Edit3 className="h-3.5 w-3.5" />}
              >
                Edit MD
              </Button>
              <CopyButton value={requirementsMd || draft} showText label="Copy MD" />
              <Button
                variant="secondary"
                size="sm"
                onClick={handleDownload}
                leftIcon={<Download className="h-3.5 w-3.5" />}
              >
                Download
              </Button>
              {onSynthesizePlan && (
                <Button
                  variant="primary"
                  size="sm"
                  onClick={onSynthesizePlan}
                  disabled={isProcessing}
                  leftIcon={<Sparkles className="h-3.5 w-3.5" />}
                >
                  Synthesize Plan
                </Button>
              )}
            </>
          )}
        </div>
      </div>

      {/* Requirements Content Body */}
      <div className="flex-1 overflow-y-auto p-6">
        {isEditing ? (
          <div className="h-full flex flex-col space-y-2">
            <textarea
              value={draft}
              onChange={(e) => setDraft(e.target.value)}
              placeholder="Enter requirements markdown..."
              className="w-full h-full min-h-[460px] p-4 bg-elevated border border-line rounded-xl font-mono text-xs text-ink-primary leading-relaxed focus:outline-none focus:ring-1 focus:ring-brand resize-none"
            />
          </div>
        ) : (
          <div className="space-y-4 max-w-4xl mx-auto">
            {viewMode === 'raw' ? (
              <pre className="p-5 rounded-xl bg-elevated/40 border border-line font-mono text-xs leading-relaxed whitespace-pre-wrap select-text text-ink-primary shadow-xs overflow-x-auto">
                {requirementsMd || draft || 'No requirements documented yet. Chat with the AI architect to formulate your architecture.'}
              </pre>
            ) : (
              <div className="p-6 rounded-xl bg-elevated/30 border border-line shadow-xs">
                <MarkdownRenderer
                  content={requirementsMd || draft || 'No requirements documented yet. Chat with the AI architect to formulate your architecture.'}
                />
              </div>
            )}

            {onSynthesizePlan && (
              <div className="p-4 rounded-xl bg-brand/10 border border-brand/30 flex flex-wrap items-center justify-between gap-4">
                <div className="flex items-center gap-3">
                  <div className="h-9 w-9 rounded-xl bg-brand/20 text-brand flex items-center justify-center shrink-0">
                    <Sparkles className="h-4 w-4" />
                  </div>
                  <div>
                    <h4 className="text-xs font-semibold text-ink-primary">Ready to generate Terraform & SQL?</h4>
                    <p className="text-[11px] text-ink-secondary">
                      Synthesize the concrete Universal IR, Terraform HCL, SQL schema, and CIS security checks directly from this specification.
                    </p>
                  </div>
                </div>
                <Button
                  variant="primary"
                  size="sm"
                  onClick={onSynthesizePlan}
                  disabled={isProcessing}
                  leftIcon={<Sparkles className="h-3.5 w-3.5" />}
                >
                  Synthesize Infrastructure Plan
                </Button>
              </div>
            )}
          </div>
        )}
      </div>
    </div>
  );
};

export const WorkspacePane: React.FC<WorkspacePaneProps> = ({
  plan,
  onApprove,
  onReject,
  onModify,
  isProcessing,
  onReexecute,
  onViewExecution,
  onViewAudit,
  driftDiff,
  requirementsMd,
  onUpdateRequirements,
  onSynthesizePlan,
}) => {
  const { toast } = useToast();
  const [activeTab, setActiveTab] = useState<'requirements' | 'overview' | 'schema' | 'code' | 'security'>(
    plan ? 'overview' : 'requirements'
  );
  const [codeSubTab, setCodeSubTab] = useState<'tf' | 'sql'>('tf');

  // Requirements editing state
  const [isEditingReq, setIsEditingReq] = useState(false);
  const [reqDraft, setReqDraft] = useState(requirementsMd || '');

  React.useEffect(() => {
    setReqDraft(requirementsMd || '');
  }, [requirementsMd]);

  // Code editing state
  const [tfCode, setTfCode] = useState(plan?.generated_terraform || '');
  const [sqlCode, setSqlCode] = useState(plan?.generated_sql || '');
  const [isEditingCode, setIsEditingCode] = useState(false);

  // Synchronize when plan changes
  React.useEffect(() => {
    if (plan) {
      setTfCode(plan.generated_terraform || '');
      setSqlCode(plan.generated_sql || '');
      setIsEditingCode(false);
    }
  }, [plan]);

  // Pre-flight Environment Snapshot state (M-15)
  const [snapshotHash, setSnapshotHash] = useState<string | null>(null);
  const [isRescanning, setIsRescanning] = useState(false);

  React.useEffect(() => {
    api.getEnvironmentSnapshot()
      .then((snap) => {
        if (snap?.snapshot_hash) setSnapshotHash(snap.snapshot_hash);
      })
      .catch(() => {});
  }, []);

  const handleRescanEnvironment = async () => {
    setIsRescanning(true);
    try {
      const snap = await api.rescanEnvironment();
      setSnapshotHash(snap.snapshot_hash);
      toast({
        title: 'Environment Rescanned',
        description: `Snapshot ${snap.snapshot_hash.substring(0, 10)} (${snap.counts.buckets} buckets, ${snap.counts.vpcs} VPCs, ${snap.counts.subnets} subnets).`,
        type: 'success',
      });
    } catch (err: any) {
      toast({
        title: 'Rescan Failed',
        description: err.message || 'Could not scan environment',
        type: 'crit',
      });
    } finally {
      setIsRescanning(false);
    }
  };

  // Dialogs
  const [showConfirmModal, setShowConfirmModal] = useState(false);
  const [confirmInput, setConfirmInput] = useState('');
  const [showModifyDialog, setShowModifyDialog] = useState(false);
  const [modifyNotes, setModifyNotes] = useState('');

  if (!plan) {
    if (requirementsMd) {
      return (
        <RequirementsView
          requirementsMd={requirementsMd}
          isEditing={isEditingReq}
          setIsEditing={setIsEditingReq}
          draft={reqDraft}
          setDraft={setReqDraft}
          onSave={onUpdateRequirements}
          onSynthesizePlan={onSynthesizePlan}
          isProcessing={isProcessing}
        />
      );
    }

    return (
      <div className="h-full flex flex-col items-center justify-center p-8 bg-surface text-center">
        <div className="p-4 rounded-2xl bg-elevated border border-line text-ink-tertiary mb-3">
          <Cloud className="h-8 w-8 text-brand" />
        </div>
        <h3 className="text-base font-semibold text-ink-primary">Workspace Standby</h3>
        <p className="text-xs text-ink-secondary max-w-sm mt-1.5 leading-relaxed">
          Chat with the AI architect in the left pane to formulate your infrastructure and database architecture. Specifications will be maintained here as Markdown.
        </p>
      </div>
    );
  }

  const { ir } = plan;

  const handleApproveClick = () => {
    if (plan.requires_confirmation_text) {
      setConfirmInput('');
      setShowConfirmModal(true);
    } else {
      onApprove(undefined, isEditingCode ? tfCode : undefined, isEditingCode ? sqlCode : undefined);
    }
  };

  const handleConfirmSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    const expected = (plan.confirmation_phrase || '').trim().toUpperCase();
    if (confirmInput.trim().toUpperCase() !== expected) {
      toast({
        title: 'Confirmation Mismatch',
        description: `Please enter "${plan.confirmation_phrase}" exactly.`,
        type: 'crit',
      });
      return;
    }
    setShowConfirmModal(false);
    onApprove(confirmInput, isEditingCode ? tfCode : undefined, isEditingCode ? sqlCode : undefined);
  };

  const handleModifySubmit = (e: React.FormEvent) => {
    e.preventDefault();
    if (!modifyNotes.trim()) return;
    setShowModifyDialog(false);
    onModify(modifyNotes);
  };

  const handleDownloadCode = (content: string, filename: string) => {
    const blob = new Blob([content], { type: 'text/plain;charset=utf-8' });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = filename;
    document.body.appendChild(a);
    a.click();
    a.remove();
    URL.revokeObjectURL(url);
    toast({
      title: 'Downloaded',
      description: `Saved ${filename}`,
      type: 'success',
    });
  };

  const tabsConfig = [
    {
      id: 'requirements',
      label: 'Requirements (MD)',
      icon: <FileText className="h-3.5 w-3.5" />,
    },
    {
      id: 'overview',
      label: `Overview (${ir.cloud?.resources?.length || 0})`,
      icon: <Cloud className="h-3.5 w-3.5" />,
    },
    ...(ir.database
      ? [
          {
            id: 'schema',
            label: `Schema (${ir.database.tables?.length || 0})`,
            icon: <Database className="h-3.5 w-3.5" />,
          },
        ]
      : []),
    {
      id: 'code',
      label: 'Code (TF / SQL)',
      icon: <Code className="h-3.5 w-3.5" />,
    },
    ...(plan.security_checks.length > 0
      ? [
          {
            id: 'security',
            label: `Security (${plan.security_checks.length})`,
            icon: <ShieldAlert className="h-3.5 w-3.5" />,
          },
        ]
      : []),
  ];

  return (
    <div className="flex flex-col h-full bg-surface overflow-hidden relative">
      {/* Workspace Header */}
      <div className="px-6 py-3.5 border-b border-line bg-surface/90 flex flex-wrap items-center justify-between gap-3 shrink-0">
        <div className="space-y-1 min-w-0">
          <div className="flex items-center gap-2 flex-wrap">
            <span className="font-mono text-xs font-semibold text-brand">
              {plan.plan_id}
            </span>
            <Chip risk={plan.risk_level} showRiskIcon />
            <span className="text-[10px] font-mono px-2 py-0.5 rounded bg-elevated border border-line text-ink-secondary uppercase">
              {plan.status}
            </span>
            <span className="text-xs text-ink-secondary">
              Target: <strong className="text-ink-primary font-mono">{ir.cloud?.provider?.toUpperCase() || 'AWS'}</strong>
            </span>
          </div>
          <h2 className="text-sm font-semibold text-ink-primary truncate max-w-xl">
            {ir.description || plan.intent}
          </h2>
        </div>

        {/* Cost & findings summary */}
        <div className="flex items-center gap-2.5 shrink-0">
          <div className="flex items-center gap-1.5 px-3 py-1 rounded-lg bg-elevated border border-line text-xs">
            <DollarSign className="h-3.5 w-3.5 text-ok" />
            <span className="text-ink-secondary">Est. Cost:</span>
            <span className="font-bold text-ok font-mono">
              {formatCurrency(plan.estimated_cost_monthly)}/mo
            </span>
          </div>
        </div>
      </div>

      {/* Drift Detection Banner */}
      {driftDiff && ((driftDiff.missing?.length || 0) > 0 || ((driftDiff.expected?.length || 0) > (driftDiff.found?.length || 0))) && (
        <div className="mx-6 mt-3 p-3 rounded-lg bg-crit/10 border border-crit/30 flex items-start gap-3 text-xs text-ink-primary shrink-0 animate-in fade-in duration-200">
          <AlertTriangle className="h-4 w-4 text-crit shrink-0 mt-0.5" />
          <div className="space-y-1">
            <p className="font-semibold text-crit">Infrastructure Drift Detected (Dry-Run)</p>
            <p className="text-ink-secondary text-[11px] leading-relaxed">
              Live infrastructure does not match this plan. Missing or deleted resources:{' '}
              <strong className="text-ink-primary font-mono">{driftDiff.missing && driftDiff.missing.length > 0 ? driftDiff.missing.join(', ') : 'Resources missing in sandbox'}</strong>.
              Review the plan and submit fresh approval below to restore resources.
            </p>
          </div>
        </div>
      )}

      {/* Tabs Bar */}
      <div className="px-6 bg-surface/50 border-b border-line shrink-0">
        <Tabs
          tabs={tabsConfig}
          activeTab={activeTab}
          onChange={(tab) => setActiveTab(tab as any)}
          variant="line"
        />
      </div>

      {/* Tab Content Body */}
      <div className="flex-1 overflow-y-auto p-6 pb-6">
        {/* TAB 0: REQUIREMENTS MD SPECIFICATION */}
        {activeTab === 'requirements' && (
          <div className="space-y-4">
            <div className="flex items-center justify-between pb-3 border-b border-line">
              <div>
                <h3 className="text-xs font-semibold text-ink-primary">Session Architecture Specification</h3>
                <p className="text-[11px] text-ink-secondary">requirements.md specification backing this plan</p>
              </div>
              <div className="flex items-center gap-2">
                <Button
                  variant="secondary"
                  size="sm"
                  onClick={() => setIsEditingReq(!isEditingReq)}
                  leftIcon={<Edit3 className="h-3 w-3" />}
                >
                  {isEditingReq ? 'Cancel' : 'Edit Spec'}
                </Button>
                {isEditingReq ? (
                  <Button
                    variant="primary"
                    size="sm"
                    onClick={() => {
                      if (onUpdateRequirements) onUpdateRequirements(reqDraft);
                      setIsEditingReq(false);
                    }}
                    leftIcon={<Check className="h-3 w-3" />}
                  >
                    Save
                  </Button>
                ) : (
                  <CopyButton value={requirementsMd || reqDraft} showText label="Copy MD" />
                )}
              </div>
            </div>
            {isEditingReq ? (
              <textarea
                value={reqDraft}
                onChange={(e) => setReqDraft(e.target.value)}
                className="w-full min-h-[460px] p-4 bg-elevated border border-line rounded-xl font-mono text-xs text-ink-primary leading-relaxed focus:outline-none focus:ring-1 focus:ring-brand resize-none"
              />
            ) : (
              <div className="p-5 rounded-xl bg-elevated/40 border border-line font-mono text-xs leading-relaxed whitespace-pre-wrap select-text text-ink-primary">
                {requirementsMd || reqDraft || 'No requirements documented yet.'}
              </div>
            )}
          </div>
        )}

        {/* TAB 1: OVERVIEW TOPOLOGY */}
        {activeTab === 'overview' && (
          <div className="space-y-6">
            <div className="flex flex-wrap items-center justify-between gap-3 text-xs text-ink-secondary bg-elevated/40 p-3 rounded-lg border border-line">
              <div className="flex items-center gap-3 flex-wrap">
                <span>Environment: <strong className="text-ink-primary uppercase">{ir.cloud?.environment || 'local'}</strong> (LocalStack Sandbox)</span>
                <span>•</span>
                <span>Region: <strong className="font-mono text-ink-primary">{ir.cloud?.region || 'us-east-1'}</strong></span>
                {snapshotHash && (
                  <>
                    <span>•</span>
                    <span className="text-[11px] font-mono text-ink-tertiary" title={`Snapshot SHA-256: ${snapshotHash}`}>
                      Env Hash: <span className="text-brand font-semibold">{snapshotHash.substring(0, 8)}</span>
                    </span>
                  </>
                )}
              </div>
              <Button
                variant="secondary"
                size="sm"
                onClick={handleRescanEnvironment}
                disabled={isRescanning}
                leftIcon={<RefreshCw className={`h-3 w-3 ${isRescanning ? 'animate-spin' : ''}`} />}
              >
                {isRescanning ? 'Scanning...' : 'Rescan now'}
              </Button>
            </div>

            {/* Visual Resource Cards Grid - Grouped by Scope Fidelity (F4) */}
            {(() => {
              const allResources = ir.cloud?.resources || [];
              const requestedResources = allResources.filter(r => !r.is_dependency);
              const dependencyResources = allResources.filter(r => r.is_dependency);

              const renderCard = (res: any, idx: number, isDep = false) => {
                const isVpc = res.type === 'virtual_network';
                const isSubnet = res.type === 'subnet';
                const isStorage = res.type === 'object_storage';
                const isDb = res.type === 'managed_database';
                const isSec = res.type === 'security_rule' || res.type === 'security_group';
                const isIgw = res.type === 'internet_gateway';
                const isRoute = res.type === 'route_table';

                return (
                  <div
                    key={idx}
                    className={`p-4 rounded-xl ${isDep ? 'bg-elevated/70 border-brand/20' : 'bg-elevated border-line'} border hover:border-line/80 transition-all flex flex-col justify-between`}
                  >
                    <div className="space-y-2.5">
                      <div className="flex items-center justify-between gap-2">
                        <div className="flex items-center gap-1.5 min-w-0">
                          {isVpc && <Network className="h-4 w-4 text-brand shrink-0" />}
                          {isSubnet && <Layers className="h-4 w-4 text-info shrink-0" />}
                          {isStorage && <HardDrive className="h-4 w-4 text-ok shrink-0" />}
                          {isDb && <Database className="h-4 w-4 text-warn shrink-0" />}
                          {(isSec || isIgw || isRoute) && <ShieldAlert className="h-4 w-4 text-high shrink-0" />}
                          <span className="text-[11px] font-bold uppercase tracking-wider text-ink-secondary truncate">
                            {res.type.replace('_', ' ')}
                          </span>
                        </div>
                        {/* Status / Dependency Chip (M-15 / F4) */}
                        {(() => {
                          if (isDep) {
                            return (
                              <span className="text-[10px] font-mono px-2 py-0.5 rounded border font-semibold shrink-0 bg-brand/10 text-brand border-brand/30">
                                DEPENDENCY
                              </span>
                            );
                          }
                          const chip = res.status_chip || res.tags?._status_chip || res.properties?._status_chip || 'NEW';
                          let chipColor = 'bg-ok/15 text-ok border-ok/30';
                          if (chip.includes('reuse')) {
                            chipColor = 'bg-info/15 text-info border-info/30';
                          } else if (chip.includes('rename')) {
                            chipColor = 'bg-warn/15 text-warn border-warn/30';
                          } else if (chip.includes('moved') || chip.includes('OVERLAP')) {
                            chipColor = 'bg-purple-500/15 text-purple-400 border-purple-500/30';
                          } else if (chip.includes('CORRECTED')) {
                            chipColor = 'bg-teal-500/15 text-teal-400 border-teal-500/30';
                          } else if (chip.includes('BLOCKED')) {
                            chipColor = 'bg-crit/15 text-crit border-crit/30';
                          }
                          return (
                            <span className={`text-[10px] font-mono px-2 py-0.5 rounded border font-semibold shrink-0 ${chipColor}`}>
                              {chip}
                            </span>
                          );
                        })()}
                      </div>

                      <h4 className="font-mono text-xs font-semibold text-ink-primary truncate" title={res.name}>
                        {res.name}
                      </h4>

                      {isDep && res.dependency_reason && (
                        <div className="text-[11px] text-brand/90 bg-brand/5 border border-brand/20 p-2 rounded-lg font-sans">
                          <span className="font-semibold text-brand">Required because: </span>
                          {res.dependency_reason.replace(/^Required because:\s*/i, '')}
                        </div>
                      )}

                      {/* Properties */}
                      {res.properties && Object.keys(res.properties).length > 0 && (
                        <div className="text-[11px] space-y-1 font-mono bg-base/60 p-2.5 rounded-lg border border-line/60">
                          {Object.entries(res.properties).map(([k, v], pIdx) => (
                            <div key={pIdx} className="flex justify-between gap-2 truncate">
                              <span className="text-ink-tertiary">{k}:</span>
                              <span className="text-ink-primary font-medium truncate" title={String(v)}>
                                {String(v)}
                              </span>
                            </div>
                          ))}
                        </div>
                      )}
                    </div>

                    {res.depends_on && res.depends_on.length > 0 && (
                      <div className="mt-3 pt-2 border-t border-line text-[10px] text-ink-secondary">
                        Depends on: <span className="font-mono text-ink-primary">{res.depends_on.join(', ')}</span>
                      </div>
                    )}
                  </div>
                );
              };

              return (
                <div className="space-y-6">
                  {/* You asked for */}
                  <div className="space-y-3">
                    <div className="flex items-center gap-2">
                      <span className="h-2 w-2 rounded-full bg-ok animate-pulse" />
                      <h4 className="text-xs font-semibold uppercase tracking-wider text-ink-primary">
                        You asked for ({requestedResources.length})
                      </h4>
                      <span className="text-[11px] text-ink-tertiary">
                        — Explicitly requested resources from your prompt
                      </span>
                    </div>
                    {requestedResources.length > 0 ? (
                      <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
                        {requestedResources.map((res, idx) => renderCard(res, idx, false))}
                      </div>
                    ) : (
                      <p className="text-xs text-ink-tertiary italic">No primary cloud resources requested.</p>
                    )}
                  </div>

                  {/* Required because (Dependencies) */}
                  {dependencyResources.length > 0 && (
                    <div className="space-y-3 pt-2 border-t border-line/60">
                      <div className="flex items-center gap-2">
                        <span className="h-2 w-2 rounded-full bg-brand" />
                        <h4 className="text-xs font-semibold uppercase tracking-wider text-brand">
                          Required because: ({dependencyResources.length})
                        </h4>
                        <span className="text-[11px] text-ink-tertiary">
                          — Strict technical dependencies required for operational safety & connectivity
                        </span>
                      </div>
                      <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
                        {dependencyResources.map((res, idx) => renderCard(res, idx, true))}
                      </div>
                    </div>
                  )}
                </div>
              );
            })()}
          </div>
        )}

        {/* TAB 2: SCHEMA (RELATIONAL / NOSQL) */}
        {activeTab === 'schema' && ir.database && (
          <SchemaViewer database={ir.database} />
        )}

        {/* TAB 3: CODE (Terraform & SQL / NoSQL) */}
        {activeTab === 'code' && (
          <div className="space-y-3">
            <div className="flex items-center justify-between">
              <div className="flex items-center gap-2">
                <button
                  type="button"
                  onClick={() => setCodeSubTab('tf')}
                  className={`px-3 py-1.5 rounded-lg text-xs font-mono font-medium transition-colors ${
                    codeSubTab === 'tf'
                      ? 'bg-brand/12 text-brand border border-brand/30'
                      : 'text-ink-secondary hover:text-ink-primary'
                  }`}
                >
                  main.tf (Terraform)
                </button>
                {plan.generated_sql && (
                  <button
                    type="button"
                    onClick={() => setCodeSubTab('sql')}
                    className={`px-3 py-1.5 rounded-lg text-xs font-mono font-medium transition-colors ${
                      codeSubTab === 'sql'
                        ? 'bg-brand/12 text-brand border border-brand/30'
                        : 'text-ink-secondary hover:text-ink-primary'
                    }`}
                  >
                    {ir.database?.provider === 'mongodb'
                      ? 'commands.js (MongoDB)'
                      : ir.database?.provider === 'mysql'
                      ? 'schema.sql (MySQL)'
                      : 'schema.sql (PostgreSQL)'}
                  </button>
                )}
              </div>


              <div className="flex items-center gap-2">
                <Button
                  variant={isEditingCode ? 'destructive' : 'secondary'}
                  size="sm"
                  onClick={() => setIsEditingCode(!isEditingCode)}
                  leftIcon={<Edit3 className="h-3.5 w-3.5" />}
                >
                  {isEditingCode ? 'Cancel Editing' : 'Edit Code'}
                </Button>

                <CopyButton
                  value={codeSubTab === 'tf' ? tfCode : sqlCode}
                  label="Copy Code"
                  showText
                  onCopy={() =>
                    toast({
                      title: 'Copied',
                      description: 'Source code copied to clipboard.',
                      type: 'success',
                    })
                  }
                />

                <Button
                  variant="outline"
                  size="sm"
                  onClick={() =>
                    handleDownloadCode(
                      codeSubTab === 'tf' ? tfCode : sqlCode,
                      codeSubTab === 'tf' ? 'main.tf' : 'schema.sql'
                    )
                  }
                  leftIcon={<Download className="h-3.5 w-3.5" />}
                >
                  Download
                </Button>
              </div>
            </div>

            {isEditingCode && (
              <div className="p-2.5 rounded-lg bg-warn/10 border border-warn/30 text-warn text-xs flex items-center justify-between">
                <span>Direct code modifications will be passed to Terraform apply upon approval.</span>
              </div>
            )}

            <div className="rounded-xl bg-base border border-line overflow-hidden font-mono text-xs">
              {codeSubTab === 'tf' ? (
                <textarea
                  value={tfCode}
                  onChange={(e) => setTfCode(e.target.value)}
                  readOnly={!isEditingCode}
                  rows={20}
                  className="w-full bg-base p-4 text-brand focus:outline-none leading-relaxed resize-y font-mono"
                />
              ) : (
                <textarea
                  value={sqlCode}
                  onChange={(e) => setSqlCode(e.target.value)}
                  readOnly={!isEditingCode}
                  rows={20}
                  className="w-full bg-base p-4 text-ok focus:outline-none leading-relaxed resize-y font-mono"
                />
              )}
            </div>
          </div>
        )}

        {/* TAB 4: SECURITY AUDITOR */}
        {activeTab === 'security' && (
          <div className="space-y-3">
            {plan.security_checks.map((chk, sIdx) => (
              <div
                key={sIdx}
                className="p-4 rounded-xl bg-elevated border border-warn/30 space-y-2"
              >
                <div className="flex items-center justify-between">
                  <div className="flex items-center gap-2">
                    <ShieldAlert className="h-4 w-4 text-warn" />
                    <span className="font-mono text-xs font-bold text-warn">{chk.rule_id}</span>
                    <Chip risk={chk.severity} />
                  </div>
                  <span className="text-xs font-mono text-ink-secondary">Resource: {chk.resource}</span>
                </div>
                <p className="text-xs text-ink-primary">{chk.message}</p>
                <div className="p-2.5 rounded-lg bg-base border border-line text-xs text-ink-secondary">
                  <strong className="text-ink-primary">Remediation: </strong>
                  {chk.remediation}
                </div>
              </div>
            ))}
          </div>
        )}
      </div>

      {/* IMPLEMENTATION PLAN STEPPER (F7) */}
      {plan.implementation_plan && plan.implementation_plan.length > 0 && (
        <div className="border-t border-line bg-surface/95 px-6 py-2.5 z-20 backdrop-blur shrink-0">
          <div className="flex items-center justify-between mb-2">
            <div className="flex items-center gap-2">
              <div className="h-5 w-5 rounded-md bg-brand/10 border border-brand/20 flex items-center justify-center text-brand">
                <ListChecks className="h-3.5 w-3.5" />
              </div>
              <span className="text-xs font-semibold text-ink-primary">Suggested Implementation Plan</span>
              <span className="text-[10px] font-mono px-1.5 py-0.5 rounded bg-brand/10 text-brand font-medium border border-brand/20">
                {plan.implementation_plan.length} Steps
              </span>
            </div>
            <span className="text-[11px] text-ink-secondary hidden sm:inline">
              Ordered execution sequence before provisioning
            </span>
          </div>

          <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-5 gap-2">
            {plan.implementation_plan.map((step, idx) => {
              const phaseColors: Record<string, string> = {
                infra: 'bg-brand/10 text-brand border-brand/20',
                config: 'bg-info/10 text-info border-info/20',
                content: 'bg-purple-500/10 text-purple-400 border-purple-500/20',
                verify: 'bg-teal-500/10 text-teal-400 border-teal-500/20',
                handoff: 'bg-ok/10 text-ok border-ok/20',
              };
              const colorClass = phaseColors[step.phase] || 'bg-elevated text-ink-secondary border-line';

              return (
                <div
                  key={step.step_number || idx}
                  className="p-2 rounded-lg bg-elevated border border-line hover:border-line/80 transition-all flex flex-col justify-between space-y-1"
                >
                  <div className="flex items-center justify-between">
                    <span className="text-[9px] font-mono font-bold text-ink-tertiary">
                      0{step.step_number || idx + 1}
                    </span>
                    <span className={`text-[8px] font-mono uppercase px-1 py-0.5 rounded border font-semibold ${colorClass}`}>
                      {step.phase}
                    </span>
                  </div>
                  <div className="font-semibold text-xs text-ink-primary truncate" title={step.name}>
                    {step.name}
                  </div>
                  <p className="text-[10px] text-ink-secondary leading-snug line-clamp-1" title={step.description}>
                    {step.description}
                  </p>
                </div>
              );
            })}
          </div>
        </div>
      )}

      {/* STICKY APPROVAL / ACTION BAR (Bottom of Workspace - M-13 State Machine) */}
      <div className="px-6 py-3 bg-surface/95 border-t border-line flex flex-wrap items-center justify-between gap-4 backdrop-blur z-20 shrink-0">
        <div className="flex items-center gap-3">
          <Chip risk={plan.risk_level} showRiskIcon />
          <span className="text-xs font-mono uppercase px-2 py-0.5 rounded bg-elevated border border-line text-ink-primary font-medium">
            {plan.status}
          </span>
          <div className="text-xs text-ink-secondary hidden sm:block">
            Estimated Cost: <strong className="text-ok font-mono">{formatCurrency(plan.estimated_cost_monthly)}/mo</strong>
          </div>
        </div>

        <div className="flex items-center gap-2.5">
          {/* State Machine: pending_approval / awaiting_approval / draft */}
          {(plan.status === 'awaiting_approval' || plan.status === 'draft' || plan.status === 'pending_approval') && (
            <>
              <Button
                variant="secondary"
                size="sm"
                onClick={() => setShowModifyDialog(true)}
                disabled={isProcessing}
                leftIcon={<Edit3 className="h-3.5 w-3.5" />}
              >
                Request Changes
              </Button>

              <Button
                variant="ghost"
                size="sm"
                onClick={onReject}
                disabled={isProcessing}
                leftIcon={<XCircle className="h-3.5 w-3.5 text-crit" />}
              >
                Reject
              </Button>

              <Button
                variant="primary"
                size="sm"
                onClick={handleApproveClick}
                disabled={isProcessing}
                loading={isProcessing}
                leftIcon={<CheckCircle2 className="h-4 w-4" />}
              >
                Approve & Execute
              </Button>
            </>
          )}

          {/* State Machine: approved / executing */}
          {(plan.status === 'approved' || plan.status === 'executing') && (
            <div className="flex items-center gap-3">
              <span className="flex items-center gap-1.5 text-xs text-brand font-medium">
                <Loader2 className="h-4 w-4 animate-spin" />
                Execution in progress...
              </span>
              {onViewExecution && (
                <Button
                  variant="secondary"
                  size="sm"
                  onClick={onViewExecution}
                  leftIcon={<ExternalLink className="h-3.5 w-3.5" />}
                >
                  Live Progress Link
                </Button>
              )}
            </div>
          )}

          {/* State Machine: completed */}
          {plan.status === 'completed' && (
            <>
              {onReexecute && (
                <Button
                  variant="primary"
                  size="sm"
                  onClick={onReexecute}
                  disabled={isProcessing}
                  loading={isProcessing}
                  leftIcon={<RefreshCw className="h-3.5 w-3.5" />}
                >
                  Re-execute
                </Button>
              )}

              <Button
                variant="secondary"
                size="sm"
                onClick={() => setShowModifyDialog(true)}
                disabled={isProcessing}
                leftIcon={<Edit3 className="h-3.5 w-3.5" />}
              >
                Clone & Modify
              </Button>

              {onViewExecution && (
                <Button
                  variant="ghost"
                  size="sm"
                  onClick={onViewExecution}
                  leftIcon={<ExternalLink className="h-3.5 w-3.5" />}
                >
                  View Execution
                </Button>
              )}

              {onViewAudit && (
                <Button
                  variant="ghost"
                  size="sm"
                  onClick={onViewAudit}
                  leftIcon={<FileText className="h-3.5 w-3.5" />}
                >
                  Audit Entry
                </Button>
              )}
            </>
          )}

          {/* State Machine: failed */}
          {plan.status === 'failed' && (
            <>
              {onReexecute && (
                <Button
                  variant="destructive"
                  size="sm"
                  onClick={onReexecute}
                  disabled={isProcessing}
                  loading={isProcessing}
                  leftIcon={<RefreshCw className="h-3.5 w-3.5" />}
                >
                  Retry (Re-execute)
                </Button>
              )}

              {onViewExecution && (
                <Button
                  variant="secondary"
                  size="sm"
                  onClick={onViewExecution}
                  leftIcon={<ExternalLink className="h-3.5 w-3.5" />}
                >
                  View Logs
                </Button>
              )}

              <Button
                variant="ghost"
                size="sm"
                onClick={() => setShowModifyDialog(true)}
                disabled={isProcessing}
                leftIcon={<Edit3 className="h-3.5 w-3.5" />}
              >
                Request Changes
              </Button>
            </>
          )}

          {/* State Machine: rejected */}
          {plan.status === 'rejected' && (
            <>
              <Button
                variant="secondary"
                size="sm"
                onClick={() => setShowModifyDialog(true)}
                disabled={isProcessing}
                leftIcon={<Edit3 className="h-3.5 w-3.5" />}
              >
                Clone & Modify
              </Button>

              {onViewAudit && (
                <Button
                  variant="ghost"
                  size="sm"
                  onClick={onViewAudit}
                  leftIcon={<FileText className="h-3.5 w-3.5" />}
                >
                  Audit Entry
                </Button>
              )}
            </>
          )}
        </div>
      </div>

      {/* High/Critical Type-to-Confirm Modal */}
      <Modal
        isOpen={showConfirmModal}
        onClose={() => setShowConfirmModal(false)}
        title="High-Risk Confirmation Required"
        description="This plan requires explicit human confirmation before execution."
        icon={<ShieldAlert className="h-5 w-5 text-crit" />}
      >
        <form onSubmit={handleConfirmSubmit} className="space-y-4">
          <p className="text-xs text-ink-secondary leading-relaxed">
            This plan carries a <strong className="text-crit uppercase">{plan.risk_level}</strong> risk rating.
            To confirm execution against LocalStack, type{' '}
            <strong className="font-mono text-ink-primary bg-base px-2 py-0.5 rounded border border-line select-all">
              {plan.confirmation_phrase}
            </strong>{' '}
            below:
          </p>

          <input
            type="text"
            value={confirmInput}
            onChange={(e) => setConfirmInput(e.target.value)}
            placeholder={`Type "${plan.confirmation_phrase}"`}
            autoFocus
            className="w-full bg-base border border-line rounded-lg px-3 py-2 text-xs font-mono text-ink-primary focus:outline-none focus:ring-2 focus:ring-crit"
          />

          <div className="flex justify-end gap-2 pt-2">
            <Button variant="secondary" size="sm" type="button" onClick={() => setShowConfirmModal(false)}>
              Cancel
            </Button>
            <Button
              variant="destructive"
              size="sm"
              type="submit"
              disabled={confirmInput.trim().toUpperCase() !== (plan.confirmation_phrase || '').toUpperCase()}
            >
              Confirm Execution
            </Button>
          </div>
        </form>
      </Modal>

      {/* Modify Requirement Dialog */}
      <Modal
        isOpen={showModifyDialog}
        onClose={() => setShowModifyDialog(false)}
        title="Request Changes to Plan"
        description="Specify architecture revisions for the AI model to re-synthesize."
        icon={<Edit3 className="h-5 w-5 text-brand" />}
      >
        <form onSubmit={handleModifySubmit} className="space-y-4">
          <textarea
            value={modifyNotes}
            onChange={(e) => setModifyNotes(e.target.value)}
            rows={4}
            autoFocus
            placeholder="e.g. Add an S3 lifecycle rule to expire objects after 30 days, or change PostgreSQL instance class to db.t3.medium..."
            className="w-full bg-base border border-line rounded-lg p-3 text-xs text-ink-primary focus:outline-none focus:ring-2 focus:ring-brand font-sans"
          />

          <div className="flex justify-end gap-2 pt-2">
            <Button variant="secondary" size="sm" type="button" onClick={() => setShowModifyDialog(false)}>
              Cancel
            </Button>
            <Button variant="primary" size="sm" type="submit" disabled={!modifyNotes.trim()}>
              Update Plan
            </Button>
          </div>
        </form>
      </Modal>
    </div>
  );
};
