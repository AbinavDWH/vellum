import React, { useState, useEffect } from 'react';
import {
  Server,
  Cpu,
  Database,
  Radio,
  Plus,
  Edit2,
  Trash2,
  Play,
  RotateCw,
  AlertTriangle,
  Shield,
  CheckCircle2,
  XCircle,
  ExternalLink,
  Zap,
  Cloud,
} from 'lucide-react';
import { Card, CardHeader, CardTitle, CardDescription, CardContent, CardFooter } from '../ui/Card';
import { Button } from '../ui/Button';
import { Chip } from '../ui/Chip';
import { useToast } from '../ui/Toast';
import { api } from '../../services/api';
import { Connection } from '../../types';
import { ConnectionDrawer } from './ConnectionDrawer';

export const ConnectionsView: React.FC = () => {
  const { toast } = useToast();

  const [connections, setConnections] = useState<Connection[]>([]);
  const [healthData, setHealthData] = useState<any>(null);
  const [loading, setLoading] = useState(true);
  const [testingId, setTestingId] = useState<string | null>(null);

  // Drawer state
  const [drawerOpen, setDrawerOpen] = useState(false);
  const [editingConnection, setEditingConnection] = useState<Connection | null>(null);

  // Affected Plans Warning Modal
  const [affectedModalOpen, setAffectedModalOpen] = useState(false);
  const [affectedPlans, setAffectedPlans] = useState<any[]>([]);
  const [pendingUpdate, setPendingUpdate] = useState<{ id: string; services: string[] } | null>(null);
  const [acknowledged, setAcknowledged] = useState(false);

  const loadData = async () => {
    setLoading(true);
    try {
      const [conns, health] = await Promise.all([
        api.getConnections().catch(() => []),
        api.getHealth().catch(() => null),
      ]);
      setConnections(conns);
      setHealthData(health);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    loadData();
  }, []);

  const handleOpenAdd = () => {
    setEditingConnection(null);
    setDrawerOpen(true);
  };

  const handleOpenEdit = (conn: Connection) => {
    setEditingConnection(conn);
    setDrawerOpen(true);
  };

  const handleDeleteConnection = async (id: string, name: string) => {
    if (!confirm(`Delete connection "${name}"? Ciphertext credentials will be purged immediately.`)) {
      return;
    }
    try {
      await api.deleteConnection(id);
      toast({
        title: 'Connection Deleted',
        description: `Credentials for "${name}" purged. Dependent plans will be blocked.`,
        type: 'info',
      });
      await loadData();
    } catch (err: any) {
      toast({
        title: 'Delete Failed',
        description: err.message || 'Could not delete connection',
        type: 'crit',
      });
    }
  };

  const handleTestConnectionCard = async (conn: Connection) => {
    setTestingId(conn.id);
    try {
      const res = await api.testConnection(conn.id);
      toast({
        title: 'Connection Test Complete',
        description: `${conn.name}: Account ${res.account_id} · ${res.services.length} probes (${res.overall_status.toUpperCase()})`,
        type: res.overall_status === 'ok' ? 'success' : 'warn',
      });
      await loadData();
    } catch (err: any) {
      toast({
        title: 'Test Failed',
        description: err.message || 'Probe checks failed',
        type: 'crit',
      });
    } finally {
      setTestingId(null);
    }
  };

  const handleForceApplyPendingUpdate = async () => {
    if (!pendingUpdate || !acknowledged) return;
    try {
      await api.updateConnectionServices(pendingUpdate.id, pendingUpdate.services, true);
      toast({
        title: 'Scope Updated',
        description: 'Services scope updated with explicit acknowledge.',
        type: 'success',
      });
      setAffectedModalOpen(false);
      setPendingUpdate(null);
      setAcknowledged(false);
      await loadData();
    } catch (err: any) {
      toast({
        title: 'Update Failed',
        description: err.message || 'Failed to apply services scope update',
        type: 'crit',
      });
    }
  };

  const getEnvBadge = (env: string) => {
    if (env === 'prod') {
      return (
        <span className="px-2 py-0.5 text-[11px] font-bold uppercase rounded bg-rose-500/20 text-rose-400 border border-rose-500/50">
          PROD
        </span>
      );
    }
    if (env === 'staging') {
      return (
        <span className="px-2 py-0.5 text-[11px] font-medium uppercase rounded bg-sky-500/20 text-sky-400 border border-sky-500/30">
          staging
        </span>
      );
    }
    return (
      <span className="px-2 py-0.5 text-[11px] font-medium uppercase rounded bg-brand/20 text-brand border border-brand/30">
        dev
      </span>
    );
  };

  const getStatusDot = (status: string) => {
    if (status === 'connected') {
      return <span className="h-2.5 w-2.5 rounded-full bg-emerald-400 shrink-0" title="Connected & Verified" />;
    }
    if (status === 'error') {
      return <span className="h-2.5 w-2.5 rounded-full bg-rose-500 shrink-0" title="Connection Error" />;
    }
    return <span className="h-2.5 w-2.5 rounded-full bg-ink-tertiary shrink-0" title="Untested" />;
  };

  return (
    <div className="space-y-8">
      {/* View Header */}
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-xl font-bold tracking-tight text-ink-primary">System & Cloud Connections</h1>
          <p className="text-xs text-ink-secondary">
            Manage AWS cloud targets, credential manager, service scopes, and persistent infrastructure engines
          </p>
        </div>
        <div className="flex items-center gap-2">
          <Button
            variant="secondary"
            size="sm"
            onClick={loadData}
            disabled={loading}
            leftIcon={<RotateCw className={`h-3.5 w-3.5 ${loading ? 'animate-spin' : ''}`} />}
          >
            Refresh
          </Button>
          <Button
            variant="primary"
            size="sm"
            onClick={handleOpenAdd}
            leftIcon={<Plus className="h-3.5 w-3.5" />}
          >
            Add Connection
          </Button>
        </div>
      </div>

      {/* Cloud Connections Section (M-17) */}
      <div className="space-y-3">
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-2">
            <Shield className="h-4 w-4 text-brand" />
            <h2 className="text-sm font-semibold text-ink-primary uppercase tracking-wider">
              Cloud Target Connections (Credentials & Scope)
            </h2>
          </div>
          <span className="text-[11px] text-ink-tertiary font-mono">
            {connections.length} configured
          </span>
        </div>

        {connections.length === 0 ? (
          <div className="p-8 text-center bg-surface border border-line rounded-xl space-y-3">
            <Server className="h-8 w-8 text-ink-tertiary mx-auto" />
            <p className="text-xs text-ink-secondary">No cloud connections configured yet.</p>
            <Button size="sm" variant="outline" onClick={handleOpenAdd}>
              Configure First Connection
            </Button>
          </div>
        ) : (
          <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
            {connections.map((conn) => (
              <Card key={conn.id} className="relative overflow-hidden flex flex-col justify-between">
                <div>
                  <CardHeader>
                    <div className="flex items-center justify-between">
                      <div className="flex items-center gap-2">
                        {getStatusDot(conn.status)}
                        <CardTitle className="font-mono text-sm">{conn.name}</CardTitle>
                        {getEnvBadge(conn.environment)}
                      </div>
                      <span className="text-[11px] font-mono text-ink-tertiary">
                        {conn.region}
                      </span>
                    </div>

                    <CardDescription className="flex items-center gap-2 pt-1 font-mono text-xs">
                      <span>Auth:</span>
                      {conn.auth_method === 'access_key' ? (
                        <span className="text-ink-primary font-semibold">
                          {conn.masked_key || 'AKIA****'}
                        </span>
                      ) : (
                        <span className="text-ink-primary">Profile ({conn.profile_name || 'default'})</span>
                      )}
                    </CardDescription>
                  </CardHeader>

                  <CardContent className="space-y-3 text-xs">

                    {/* Services Chips */}
                    <div>
                      <span className="text-[11px] font-medium text-ink-tertiary uppercase block mb-1.5">
                        Allowed Services Scope ({conn.services.length})
                      </span>
                      <div className="flex flex-wrap gap-1">
                        {conn.services.map((svc) => (
                          <span
                            key={svc}
                            className="px-2 py-0.5 rounded text-[11px] font-mono font-medium bg-canvas border border-line text-ink-secondary"
                          >
                            {svc}
                          </span>
                        ))}
                      </div>
                    </div>

                    {/* Probed Details if available */}
                    {conn.account_id && (
                      <div className="flex justify-between py-1 border-t border-line text-[11px] text-ink-tertiary font-mono">
                        <span>Account: {conn.account_id}</span>
                        {conn.last_tested_at && (
                          <span>Verified {new Date(conn.last_tested_at).toLocaleDateString()}</span>
                        )}
                      </div>
                    )}
                  </CardContent>
                </div>

                <CardFooter className="justify-between border-t border-line pt-3 mt-3">
                  <div className="flex items-center gap-1.5">
                    <Button
                      size="sm"
                      variant="outline"
                      loading={testingId === conn.id}
                      onClick={() => handleTestConnectionCard(conn)}
                      leftIcon={<Play className="h-3 w-3" />}
                    >
                      Test
                    </Button>
                    <Button
                      size="sm"
                      variant="outline"
                      onClick={() => handleOpenEdit(conn)}
                      leftIcon={<Edit2 className="h-3 w-3" />}
                    >
                      Edit
                    </Button>
                  </div>

                  <Button
                    size="sm"
                    variant="ghost"
                    onClick={() => handleDeleteConnection(conn.id, conn.name)}
                    className="text-rose-400 hover:text-rose-300 hover:bg-rose-500/10 cursor-pointer"
                  >
                    <Trash2 className="h-3.5 w-3.5" />
                  </Button>
                </CardFooter>
              </Card>
            ))}
          </div>
        )}
      </div>

      {/* System Infrastructure Connections Section */}
      <div className="space-y-3">
        <h2 className="text-sm font-semibold text-ink-primary uppercase tracking-wider">
          Runtime Core Engines
        </h2>
        <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4">
          {/* 1. Groq Cloud Engine */}
          <Card>
            <CardHeader>
              <div className="flex items-center justify-between">
                <div className="flex items-center gap-2">
                  <Zap className="h-5 w-5 text-amber-500" />
                  <CardTitle>Groq Cloud API</CardTitle>
                </div>
                <Chip variant={healthData?.groq_online ? 'ok' : 'crit'}>
                  {healthData?.groq_online ? 'Online' : 'Offline'}
                </Chip>
              </div>
              <CardDescription>Ultra-fast LPU inference (Primary)</CardDescription>
            </CardHeader>
            <CardContent className="space-y-2 text-xs">
              <div className="flex justify-between py-1 border-b border-line">
                <span className="text-ink-secondary">Endpoint:</span>
                <span className="font-mono text-ink-primary truncate max-w-[140px]" title="https://api.groq.com/openai/v1">api.groq.com</span>
              </div>
              <div className="flex justify-between py-1 border-b border-line">
                <span className="text-ink-secondary">Model:</span>
                <span className="font-mono text-brand truncate max-w-[150px]" title="openai/gpt-oss-120b">
                  gpt-oss-120b
                </span>
              </div>
            </CardContent>
          </Card>

          {/* 2. LM Studio Engine */}
          <Card>
            <CardHeader>
              <div className="flex items-center justify-between">
                <div className="flex items-center gap-2">
                  <Cpu className="h-5 w-5 text-brand" />
                  <CardTitle>LM Studio Local</CardTitle>
                </div>
                <Chip variant={healthData?.lm_studio_online ? 'ok' : 'crit'}>
                  {healthData?.lm_studio_online ? 'Online' : 'Offline'}
                </Chip>
              </div>
              <CardDescription>Local offline & private fallback</CardDescription>
            </CardHeader>
            <CardContent className="space-y-2 text-xs">
              <div className="flex justify-between py-1 border-b border-line">
                <span className="text-ink-secondary">Endpoint:</span>
                <span className="font-mono text-ink-primary">localhost:1234/v1</span>
              </div>
              <div className="flex justify-between py-1 border-b border-line">
                <span className="text-ink-secondary">Active Model:</span>
                <span className="font-mono text-brand truncate max-w-[150px]" title={healthData?.active_model}>
                  {healthData?.active_model || 'Detecting...'}
                </span>
              </div>
            </CardContent>
          </Card>

          {/* 2. PostgreSQL Engine */}
          <Card>
            <CardHeader>
              <div className="flex items-center justify-between">
                <div className="flex items-center gap-2">
                  <Database className="h-5 w-5 text-ok" />
                  <CardTitle>PostgreSQL Engine</CardTitle>
                </div>
                <Chip variant="ok">Ready</Chip>
              </div>
              <CardDescription>Relational DDL & schema target</CardDescription>
            </CardHeader>
            <CardContent className="space-y-2 text-xs">
              <div className="flex justify-between py-1 border-b border-line">
                <span className="text-ink-secondary">Database:</span>
                <span className="font-mono text-ink-primary">vellum</span>
              </div>
              <div className="flex justify-between py-1 border-b border-line">
                <span className="text-ink-secondary">Driver:</span>
                <span className="text-ok">PostgreSQL 15+ / SQLAlchemy</span>
              </div>
            </CardContent>
          </Card>

          {/* 3. WebSocket Terminal Protocol */}
          <Card>
            <CardHeader>
              <div className="flex items-center justify-between">
                <div className="flex items-center gap-2">
                  <Radio className="h-5 w-5 text-info" />
                  <CardTitle>WebSocket Terminal</CardTitle>
                </div>
                <Chip variant="info">Standby</Chip>
              </div>
              <CardDescription>Live execution stream</CardDescription>
            </CardHeader>
            <CardContent className="space-y-2 text-xs">
              <div className="flex justify-between py-1 border-b border-line">
                <span className="text-ink-secondary">Channel:</span>
                <span className="font-mono text-ink-primary">/ws/execution/&#123;id&#125;</span>
              </div>
              <div className="flex justify-between py-1 border-b border-line">
                <span className="text-ink-secondary">Fallback:</span>
                <span className="text-ok">Automatic REST polling</span>
              </div>
            </CardContent>
          </Card>
        </div>
      </div>

      {/* Add / Edit Connection Drawer */}
      <ConnectionDrawer
        isOpen={drawerOpen}
        onClose={() => setDrawerOpen(false)}
        connection={editingConnection}
        onSaved={loadData}
      />

      {/* Affected Plans Warning Modal */}
      {affectedModalOpen && (
        <div className="fixed inset-0 z-50 flex items-center justify-center p-4">
          <div className="fixed inset-0 bg-black/70 backdrop-blur-xs" onClick={() => setAffectedModalOpen(false)} />
          <div className="relative w-full max-w-lg bg-surface border border-line rounded-xl shadow-2xl p-5 space-y-4 z-10 animate-in fade-in duration-150">
            <div className="flex items-center gap-2.5 text-warn">
              <AlertTriangle className="h-5 w-5 shrink-0" />
              <h3 className="text-sm font-semibold text-ink-primary">
                Warning: Existing Managed Resources Affected
              </h3>
            </div>
            <p className="text-xs text-ink-secondary">
              The services you are removing are currently referenced by active or completed infrastructure plans.
              Removing them will prevent future management of these resources.
            </p>

            <div className="max-h-40 overflow-y-auto space-y-1.5 p-2 bg-canvas rounded border border-line text-xs font-mono">
              {affectedPlans.map((ap, idx) => (
                <div key={idx} className="flex justify-between items-center text-ink-primary">
                  <span>{ap.resource_name} ({ap.resource_type})</span>
                  <span className="text-ink-tertiary">{ap.plan_id}</span>
                </div>
              ))}
            </div>

            <label className="flex items-center gap-2 text-xs text-ink-primary cursor-pointer pt-2">
              <input
                type="checkbox"
                checked={acknowledged}
                onChange={(e) => setAcknowledged(e.target.checked)}
                className="rounded border-line text-brand focus:ring-0"
              />
              <span>I acknowledge that managed resources may become unreachable</span>
            </label>

            <div className="flex items-center justify-end gap-2 pt-3 border-t border-line">
              <Button size="sm" variant="outline" onClick={() => setAffectedModalOpen(false)}>
                Cancel
              </Button>
              <Button
                size="sm"
                variant="primary"
                disabled={!acknowledged}
                onClick={handleForceApplyPendingUpdate}
              >
                Force Apply
              </Button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
};
