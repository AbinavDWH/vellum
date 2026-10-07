import React, { useState, useEffect } from 'react';
import {
  Settings,
  Shield,
  Sliders,
  Save,
  Check,
  BookOpen,
  RefreshCw,
  Zap,
  AlertTriangle,
  CheckCircle2,
  AlertOctagon,
  Cpu,
  Power,
} from 'lucide-react';
import { Card, CardHeader, CardTitle, CardDescription, CardContent, CardFooter } from '../ui/Card';
import { Button } from '../ui/Button';
import { Chip } from '../ui/Chip';
import { useToast } from '../ui/Toast';
import { cn } from '../../lib/utils';
import { api } from '../../services/api';
import { RemediationKBItem } from '../../types';

export const SettingsView: React.FC = () => {
  const { toast } = useToast();
  const [defaultProvider, setDefaultProvider] = useState('aws');
  const [defaultRegion, setDefaultRegion] = useState('us-east-1');
  const [autoVerify, setAutoVerify] = useState(true);
  const [strictApproval, setStrictApproval] = useState(true);
  const [logLevel, setLogLevel] = useState('info');

  // Remediation KB state
  const [remediations, setRemediations] = useState<RemediationKBItem[]>([]);
  const [loadingRemediations, setLoadingRemediations] = useState<boolean>(true);
  const [updatingId, setUpdatingId] = useState<number | null>(null);

  const fetchRemediations = async () => {
    setLoadingRemediations(true);
    try {
      const items = await api.getRemediations();
      setRemediations(items);
    } catch (err: any) {
      toast({
        title: 'Failed to load playbooks',
        description: err.message || 'Could not fetch Remediation Knowledge Base',
        type: 'crit',
      });
    } finally {
      setLoadingRemediations(false);
    }
  };

  useEffect(() => {
    fetchRemediations();
  }, []);

  const handleTogglePlaybook = async (item: RemediationKBItem) => {
    setUpdatingId(item.id);
    const nextState = !item.enabled;
    try {
      const updated = await api.updateRemediation(item.id, { enabled: nextState });
      setRemediations((prev) => prev.map((r) => (r.id === item.id ? updated : r)));
      toast({
        title: nextState ? 'Playbook enabled' : 'Playbook disabled',
        description: `Remediation playbook for ${item.signature} is now ${nextState ? 'active' : 'paused'}.`,
        type: 'success',
      });
    } catch (err: any) {
      toast({
        title: 'Update failed',
        description: err.message || 'Failed to update remediation status',
        type: 'crit',
      });
    } finally {
      setUpdatingId(null);
    }
  };

  const handleSave = () => {
    toast({
      title: 'Settings saved',
      description: 'System preferences have been updated.',
      type: 'success',
    });
  };

  // Metrics summary
  const totalPlaybooks = remediations.length;
  const activeCount = remediations.filter((r) => r.enabled && !r.circuit_broken).length;
  const promotedCount = remediations.filter((r) => r.is_promoted).length;
  const brokenCount = remediations.filter((r) => r.circuit_broken || r.cross_plan_failures >= 3).length;

  return (
    <div className="space-y-6 max-w-5xl">
      {/* View Header */}
      <div>
        <h1 className="text-xl font-bold tracking-tight text-ink-primary">Control Plane Settings</h1>
        <p className="text-xs text-ink-secondary">
          Configure default cloud generation parameters, security thresholds, and self-healing remediation rules
        </p>
      </div>

      <div className="space-y-6">
        {/* Cloud Defaults */}
        <Card>
          <CardHeader>
            <div className="flex items-center gap-2">
              <Sliders className="h-5 w-5 text-brand" />
              <CardTitle>Architecture Defaults</CardTitle>
            </div>
            <CardDescription>
              Default cloud provider and environment configuration for new natural language prompts
            </CardDescription>
          </CardHeader>
          <CardContent className="space-y-4 text-xs">
            <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
              <div className="space-y-1.5">
                <label className="font-semibold text-ink-primary">Default Cloud Provider</label>
                <select
                  value={defaultProvider}
                  onChange={(e) => setDefaultProvider(e.target.value)}
                  className="w-full bg-elevated border border-line rounded-lg px-3 py-2 text-ink-primary focus:outline-none focus:ring-2 focus:ring-brand"
                >
                  <option value="aws">AWS (Amazon Web Services)</option>
                  <option value="azure">Azure (Microsoft Azure)</option>
                  <option value="gcp">GCP (Google Cloud Platform)</option>
                </select>
              </div>

              <div className="space-y-1.5">
                <label className="font-semibold text-ink-primary">Default AWS Region</label>
                <input
                  type="text"
                  value={defaultRegion}
                  onChange={(e) => setDefaultRegion(e.target.value)}
                  className="w-full bg-elevated border border-line rounded-lg px-3 py-2 text-ink-primary font-mono focus:outline-none focus:ring-2 focus:ring-brand"
                />
              </div>
            </div>

            <div className="flex items-center justify-between pt-2">
              <div>
                <div className="font-semibold text-ink-primary">Auto-Verify After Execution</div>
                <div className="text-ink-secondary text-[11px]">
                  Automatically audit LocalStack resources and detect drift upon Terraform apply completion
                </div>
              </div>
              <input
                type="checkbox"
                checked={autoVerify}
                onChange={(e) => setAutoVerify(e.target.checked)}
                className="h-4 w-4 accent-brand rounded cursor-pointer"
              />
            </div>
          </CardContent>
        </Card>

        {/* Safety & Human in the Loop */}
        <Card>
          <CardHeader>
            <div className="flex items-center gap-2">
              <Shield className="h-5 w-5 text-warn" />
              <CardTitle>Safety & Human-in-the-Loop Controls</CardTitle>
            </div>
            <CardDescription>
              Governance rules preventing unintended infrastructure modification
            </CardDescription>
          </CardHeader>
          <CardContent className="space-y-4 text-xs">
            <div className="flex items-center justify-between">
              <div>
                <div className="font-semibold text-ink-primary">Strict Type-to-Confirm for High/Critical Risk</div>
                <div className="text-ink-secondary text-[11px]">
                  Requires typing an exact confirmation phrase before any destructive or production-risk operation
                </div>
              </div>
              <input
                type="checkbox"
                checked={strictApproval}
                disabled
                className="h-4 w-4 accent-brand rounded cursor-not-allowed opacity-80"
              />
            </div>

            <div className="space-y-1.5 pt-2">
              <label className="font-semibold text-ink-primary">Terminal Log Streaming Level</label>
              <select
                value={logLevel}
                onChange={(e) => setLogLevel(e.target.value)}
                className="w-full sm:w-64 bg-elevated border border-line rounded-lg px-3 py-2 text-ink-primary focus:outline-none focus:ring-2 focus:ring-brand"
              >
                <option value="debug">DEBUG (Verbose Terraform output)</option>
                <option value="info">INFO (Standard execution stages)</option>
                <option value="warn">WARN (Warnings and notices only)</option>
                <option value="error">ERROR (Failures only)</option>
              </select>
            </div>
          </CardContent>
          <CardFooter className="justify-end">
            <Button variant="primary" size="sm" onClick={handleSave} leftIcon={<Save className="h-3.5 w-3.5" />}>
              Save Preferences
            </Button>
          </CardFooter>
        </Card>

        {/* Remediation Knowledge Base (M-14) */}
        <Card>
          <CardHeader>
            <div className="flex items-center justify-between">
              <div className="flex items-center gap-2">
                <BookOpen className="h-5 w-5 text-brand" />
                <div>
                  <CardTitle>Remediation Knowledge Base (M-14)</CardTitle>
                  <CardDescription className="mt-1">
                    Deterministic playbooks and promoted auto-healing policies. When an error matches a signature,
                    the execution engine applies the active playbook or consults the LLM fix proposer.
                  </CardDescription>
                </div>
              </div>
              <Button
                variant="ghost"
                size="sm"
                onClick={fetchRemediations}
                disabled={loadingRemediations}
                leftIcon={<RefreshCw className={cn('h-3.5 w-3.5', loadingRemediations && 'animate-spin')} />}
              >
                Refresh
              </Button>
            </div>
          </CardHeader>
          <CardContent className="space-y-4">
            {/* Quick Metrics Bar */}
            <div className="grid grid-cols-2 sm:grid-cols-4 gap-3 text-xs">
              <div className="p-3 rounded-lg bg-elevated/70 border border-line">
                <div className="text-ink-secondary text-[11px] font-medium">Total Playbooks</div>
                <div className="text-base font-bold text-ink-primary mt-0.5">{totalPlaybooks}</div>
              </div>
              <div className="p-3 rounded-lg bg-elevated/70 border border-line">
                <div className="text-ink-secondary text-[11px] font-medium">Active & Healthy</div>
                <div className="text-base font-bold text-ok mt-0.5">{activeCount}</div>
              </div>
              <div className="p-3 rounded-lg bg-elevated/70 border border-line">
                <div className="text-ink-secondary text-[11px] font-medium">Promoted (Zero LLM)</div>
                <div className="text-base font-bold text-brand mt-0.5">{promotedCount}</div>
              </div>
              <div className="p-3 rounded-lg bg-elevated/70 border border-line">
                <div className="text-ink-secondary text-[11px] font-medium">Circuit Tripped</div>
                <div className={cn('text-base font-bold mt-0.5', brokenCount > 0 ? 'text-crit' : 'text-ink-secondary')}>
                  {brokenCount}
                </div>
              </div>
            </div>

            {/* Table */}
            {loadingRemediations && remediations.length === 0 ? (
              <div className="py-12 flex flex-col items-center justify-center text-ink-secondary text-xs">
                <RefreshCw className="h-6 w-6 animate-spin mb-2 text-brand" />
                <span>Loading remediation playbooks...</span>
              </div>
            ) : remediations.length === 0 ? (
              <div className="py-8 text-center text-ink-secondary text-xs">
                No remediation playbooks found in database.
              </div>
            ) : (
              <div className="overflow-x-auto rounded-lg border border-line">
                <table className="w-full text-left text-xs">
                  <thead className="bg-elevated/80 border-b border-line text-ink-secondary font-semibold">
                    <tr>
                      <th className="py-2.5 px-3">Error Signature & Class</th>
                      <th className="py-2.5 px-3">Strategy</th>
                      <th className="py-2.5 px-3">Reliability</th>
                      <th className="py-2.5 px-3">Status & Circuit</th>
                      <th className="py-2.5 px-3 text-right">Action</th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-line">
                    {remediations.map((item) => {
                      const isBroken = item.circuit_broken || item.cross_plan_failures >= 3;
                      return (
                        <tr key={item.id} className="hover:bg-elevated/40 transition-colors">
                          <td className="py-3 px-3">
                            <div className="flex items-center gap-2">
                              <span className="font-mono font-medium text-ink-primary">{item.signature}</span>
                              <Chip
                                variant={
                                  item.error_class === 'auth' || item.error_class === 'quota'
                                    ? 'crit'
                                    : item.error_class === 'transient'
                                    ? 'warn'
                                    : 'neutral'
                                }
                                className="text-[10px] px-1.5 py-0"
                              >
                                {item.error_class}
                              </Chip>
                            </div>
                            {item.description && (
                              <p className="text-[11px] text-ink-secondary mt-0.5 leading-relaxed max-w-md">
                                {item.description}
                              </p>
                            )}
                          </td>
                          <td className="py-3 px-3">
                            <div className="flex flex-col gap-1 items-start">
                              <span className="font-mono text-[11px] text-ink-primary bg-elevated px-1.5 py-0.5 rounded border border-line">
                                {item.fix_type}
                              </span>
                              {item.is_promoted && (
                                <Chip variant="brand" className="text-[9px] px-1.5 py-0">
                                  Promoted Playbook
                                </Chip>
                              )}
                            </div>
                          </td>
                          <td className="py-3 px-3">
                            <div className="text-[11px] space-y-0.5">
                              <div className="text-ok font-medium flex items-center gap-1">
                                <Check className="h-3 w-3" />
                                {item.success_count} healed
                              </div>
                              <div className="text-ink-secondary text-[10px]">
                                {item.failure_count} fails · v{item.version}
                              </div>
                            </div>
                          </td>
                          <td className="py-3 px-3">
                            {isBroken ? (
                              <Chip variant="crit" icon={<AlertOctagon className="h-3 w-3" />}>
                                Circuit Tripped ({item.cross_plan_failures} fails)
                              </Chip>
                            ) : item.enabled ? (
                              <Chip variant="ok" icon={<CheckCircle2 className="h-3 w-3" />}>
                                Active
                              </Chip>
                            ) : (
                              <Chip variant="neutral" icon={<Power className="h-3 w-3" />}>
                                Disabled
                              </Chip>
                            )}
                          </td>
                          <td className="py-3 px-3 text-right">
                            <Button
                              variant={item.enabled ? 'outline' : 'primary'}
                              size="sm"
                              className="text-xs py-1 px-2.5 h-7"
                              disabled={updatingId === item.id}
                              onClick={() => handleTogglePlaybook(item)}
                            >
                              {updatingId === item.id ? (
                                <RefreshCw className="h-3 w-3 animate-spin" />
                              ) : item.enabled ? (
                                'Disable'
                              ) : (
                                'Enable'
                              )}
                            </Button>
                          </td>
                        </tr>
                      );
                    })}
                  </tbody>
                </table>
              </div>
            )}
          </CardContent>
        </Card>
      </div>
    </div>
  );
};

