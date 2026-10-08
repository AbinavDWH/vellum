import React, { useState, useEffect } from 'react';
import {
  X,
  Eye,
  EyeOff,
  CheckCircle2,
  XCircle,
  AlertTriangle,
  Play,
  Save,
  Shield,
  Server,
  Layers,
  Check,
} from 'lucide-react';
import { Button } from '../ui/Button';
import { Chip } from '../ui/Chip';
import { useToast } from '../ui/Toast';
import { api } from '../../services/api';
import { Connection, ConnectionTestResult, ServiceProbeResult } from '../../types';

interface ConnectionDrawerProps {
  isOpen: boolean;
  onClose: () => void;
  connection?: Connection | null;
  onSaved: () => void;
}

const ALL_SERVICES = [
  's3',
  'ec2',
  'vpc',
  'rds',
  'iam',
  'sts',
  'cloudwatch',
  'lambda',
  'dynamodb',
];

const PRESETS = {
  recommended: ['s3', 'ec2', 'vpc', 'rds', 'iam', 'sts'],
  all: ALL_SERVICES,
  storage: ['s3', 'rds', 'dynamodb'],
};

const REGIONS = [
  'us-east-1',
  'us-east-2',
  'us-west-1',
  'us-west-2',
  'eu-west-1',
  'eu-central-1',
  'ap-southeast-1',
];

export const ConnectionDrawer: React.FC<ConnectionDrawerProps> = ({
  isOpen,
  onClose,
  connection,
  onSaved,
}) => {
  const { toast } = useToast();
  const isEdit = Boolean(connection);

  const [provider, setProvider] = useState('aws');
  const [environment, setEnvironment] = useState<'dev' | 'staging' | 'prod'>('prod');
  const [name, setName] = useState('');
  const [authMethod, setAuthMethod] = useState<'access_key' | 'profile'>('access_key');
  const [profileName, setProfileName] = useState('default');
  const [accessKeyId, setAccessKeyId] = useState('');
  const [secretAccessKey, setSecretAccessKey] = useState('');
  const [showSecret, setShowSecret] = useState(false);
  const [region, setRegion] = useState('us-east-1');
  const [services, setServices] = useState<string[]>(PRESETS.recommended);
  const [confirmName, setConfirmName] = useState('');

  // Testing state
  const [isTesting, setIsTesting] = useState(false);
  const [testResult, setTestResult] = useState<ConnectionTestResult | null>(null);
  const [testError, setTestError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    if (connection) {
      setName(connection.name);
      setProvider(connection.provider || 'aws');
      const env = connection.environment === 'local' ? 'dev' : (connection.environment || 'dev');
      setEnvironment(env as 'dev' | 'staging' | 'prod');
      setAuthMethod(connection.auth_method || 'access_key');
      setProfileName(connection.profile_name || 'default');
      setAccessKeyId(connection.key_prefix && connection.key_last4 ? `${connection.key_prefix}123456789012${connection.key_last4}` : '');
      setSecretAccessKey(''); // Never pre-fill secret
      setRegion(connection.region || 'us-east-1');
      setServices(connection.services || PRESETS.recommended);
      setConfirmName('');
      setTestResult(null);
      setTestError(null);
    } else {
      setName('');
      setProvider('aws');
      setEnvironment('dev');
      setAuthMethod('access_key');
      setProfileName('default');
      setAccessKeyId('');
      setSecretAccessKey('');
      setRegion('us-east-1');
      setServices(PRESETS.recommended);
      setConfirmName('');
      setTestResult(null);
      setTestError(null);
    }
  }, [connection, isOpen]);

  if (!isOpen) return null;

  // Validation rules
  const accessKeyRegex = /^(AKIA|ASIA)[0-9A-Z]{16}$/;
  const isAccessKeyValid = authMethod === 'profile' || (isEdit && !accessKeyId) || accessKeyRegex.test(accessKeyId.trim());
  const accessKeyDirty = accessKeyId.length > 0;
  const accessKeyError = accessKeyDirty && !accessKeyRegex.test(accessKeyId.trim())
    ? 'Access Key ID must start with AKIA or ASIA and be exactly 20 uppercase alphanumeric characters.'
    : null;

  const secretDirty = secretAccessKey.length > 0;
  const secretRegex = /^[A-Za-z0-9/+=]{40}$/;
  const isSecretValid = authMethod === 'profile' || (isEdit && !secretDirty) || (secretDirty && secretRegex.test(secretAccessKey.trim()));
  const secretError = secretDirty && !secretRegex.test(secretAccessKey.trim())
    ? 'Secret Access Key must be exactly 40 characters [A-Za-z0-9/+=].'
    : null;

  const isProd = environment === 'prod';
  const isProdConfirmed = !isProd || (confirmName.trim() === name.trim() && name.trim().length > 0);

  const canTest =
    name.trim().length > 0 &&
    (authMethod === 'profile' || (isAccessKeyValid && (isEdit || secretDirty)));

  const canSave =
    name.trim().length > 0 &&
    isAccessKeyValid &&
    isSecretValid &&
    isProdConfirmed &&
    (authMethod === 'profile' || isEdit || (accessKeyDirty && secretDirty)) &&
    !saving;

  const toggleService = (svc: string) => {
    setServices((prev) =>
      prev.includes(svc) ? prev.filter((s) => s !== svc) : [...prev, svc]
    );
  };

  const handleRunTest = async () => {
    setIsTesting(true);
    setTestError(null);
    try {
      const payload = {
        name,
        provider,
        environment,
        region,
        auth_method: authMethod,
        access_key_id: accessKeyId.trim() || undefined,
        secret_access_key: secretAccessKey.trim() || undefined,
        services,
      };
      const result = await api.testConnection(connection?.id, payload);
      setTestResult(result);
      if (result.overall_status === 'ok') {
        toast({
          title: 'Connection Verified',
          description: `STS Identity: ${result.account_id} (${result.services.length} probes successful)`,
          type: 'success',
        });
      } else {
        toast({
          title: 'Probe Notice',
          description: `Probes completed with status: ${result.overall_status}. Review individual service statuses below.`,
          type: 'warn',
        });
      }
    } catch (err: any) {
      setTestError(err.message || 'Connection test failed');
      toast({
        title: 'Connection Failed',
        description: err.message || 'Could not verify credentials with cloud provider',
        type: 'crit',
      });
    } finally {
      setIsTesting(false);
    }
  };

  const handleSave = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!canSave) return;

    setSaving(true);
    try {
      const payload: any = {
        name: name.trim(),
        provider,
        environment,
        auth_method: authMethod,
        profile_name: authMethod === 'profile' ? profileName.trim() : undefined,
        region,
        services,
        confirm_name: isProd ? confirmName.trim() : undefined,
      };

      if (accessKeyId.trim()) {
        payload.access_key_id = accessKeyId.trim();
      }
      if (secretAccessKey.trim()) {
        payload.secret_access_key = secretAccessKey.trim();
      }

      if (isEdit && connection) {
        await api.updateConnection(connection.id, payload);
        toast({
          title: 'Connection Updated',
          description: `Saved changes to "${name}". Credentials securely encrypted.`,
          type: 'success',
        });
      } else {
        await api.createConnection(payload);
        toast({
          title: 'Connection Created',
          description: `Connection "${name}" configured with encrypted credentials.`,
          type: 'success',
        });
      }

      onSaved();
      onClose();
    } catch (err: any) {
      toast({
        title: 'Save Failed',
        description: err.message || 'Could not save connection credentials',
        type: 'crit',
      });
    } finally {
      setSaving(false);
    }
  };

  return (
    <div className="fixed inset-0 z-50 flex">
      {/* Backdrop */}
      <div
        className="fixed inset-0 bg-black/60 backdrop-blur-xs transition-opacity"
        onClick={onClose}
      />

      {/* Drawer Container */}
      <div
        data-testid="connection-drawer"
        className="relative ml-auto w-full max-w-xl h-full bg-surface border-l border-line shadow-2xl flex flex-col z-10 animate-in slide-in-from-right duration-200"
      >
        {/* Header */}
        <div className="p-4 border-b border-line flex items-center justify-between">
          <div className="flex items-center gap-2">
            <Server className="h-5 w-5 text-brand" />
            <div>
              <h2 className="text-sm font-semibold text-ink-primary">
                {isEdit ? 'Edit Connection' : 'Add Connection'}
              </h2>
              <p className="text-[11px] text-ink-tertiary">
                Credentials are encrypted at rest and never exposed to LLM or logs
              </p>
            </div>
          </div>
          <button
            onClick={onClose}
            className="p-1 rounded text-ink-tertiary hover:text-ink-primary hover:bg-elevated cursor-pointer"
          >
            <X className="h-4 w-4" />
          </button>
        </div>

        {/* Form Body */}
        <form onSubmit={handleSave} className="flex-1 overflow-y-auto p-5 space-y-5">
          {/* Provider & Environment */}
          <div className="grid grid-cols-2 gap-4">
            <div>
              <label className="block text-xs font-medium text-ink-secondary mb-1.5">
                Provider
              </label>
              <select
                value={provider}
                onChange={(e) => setProvider(e.target.value)}
                className="w-full bg-canvas border border-line rounded-md px-3 py-1.5 text-xs text-ink-primary focus:outline-hidden focus:border-brand"
              >
                <option value="aws">AWS</option>
              </select>
            </div>

            <div>
              <label className="block text-xs font-medium text-ink-secondary mb-1.5">
                Environment
              </label>
              <div className="flex items-center gap-1.5 pt-0.5">
                {(['dev', 'staging', 'prod'] as const).map((env) => {
                  const selected = environment === env;
                  const isEnvProd = env === 'prod';
                  return (
                    <button
                      key={env}
                      type="button"
                      onClick={() => setEnvironment(env)}
                      className={`px-2.5 py-1 text-xs font-semibold rounded-md border transition-all cursor-pointer ${
                        selected
                          ? isEnvProd
                            ? 'bg-rose-500/20 border-rose-500 text-rose-400 shadow-xs'
                            : 'bg-brand/20 border-brand text-brand shadow-xs'
                          : 'bg-canvas border-line text-ink-tertiary hover:text-ink-primary'
                      }`}
                    >
                      {isEnvProd ? 'PROD' : env.toUpperCase()}
                    </button>
                  );
                })}
              </div>
            </div>
          </div>

          {/* Connection Name */}
          <div>
            <label className="block text-xs font-medium text-ink-secondary mb-1.5">
              Connection Name
            </label>
            <input
              type="text"
              placeholder="e.g. sandbox-main"
              value={name}
              onChange={(e) => setName(e.target.value)}
              className="w-full bg-canvas border border-line rounded-md px-3 py-1.5 text-xs text-ink-primary focus:outline-hidden focus:border-brand font-mono"
              required
            />
          </div>

          {/* PROD Typed Confirmation Warning */}
          {isProd && (
            <div className="p-3 bg-rose-500/10 border border-rose-500/30 rounded-lg space-y-2">
              <div className="flex items-center gap-2 text-rose-400 text-xs font-semibold">
                <AlertTriangle className="h-4 w-4 shrink-0" />
                <span>Production Environment Protection</span>
              </div>
              <p className="text-[11px] text-ink-secondary">
                Actions targeting PROD require strict confirmation phrases and mandatory human approval gates.
                Type the connection name below to confirm.
              </p>
              <input
                type="text"
                placeholder={`Type "${name || 'connection name'}" to confirm`}
                value={confirmName}
                onChange={(e) => setConfirmName(e.target.value)}
                className="w-full bg-canvas border border-rose-500/40 rounded px-2.5 py-1 text-xs text-ink-primary focus:outline-hidden focus:border-rose-400 font-mono"
              />
            </div>
          )}

          {/* Auth Method */}
          <div>
            <label className="block text-xs font-medium text-ink-secondary mb-1.5">
              Auth Method
            </label>
            <div className="flex items-center gap-4 text-xs text-ink-primary">
              <label className="flex items-center gap-2 cursor-pointer">
                <input
                  type="radio"
                  name="authMethod"
                  value="access_key"
                  checked={authMethod === 'access_key'}
                  onChange={() => setAuthMethod('access_key')}
                  className="text-brand focus:ring-0"
                />
                <span>Access Key Pair</span>
              </label>
              <label className="flex items-center gap-2 cursor-pointer">
                <input
                  type="radio"
                  name="authMethod"
                  value="profile"
                  checked={authMethod === 'profile'}
                  onChange={() => setAuthMethod('profile')}
                  className="text-brand focus:ring-0"
                />
                <span>Local Profile (~/.aws)</span>
              </label>
            </div>
          </div>

          {/* Credentials Inputs */}
          {authMethod === 'access_key' ? (
            <div className="space-y-3 p-3 bg-canvas/60 rounded-lg border border-line">
              {/* Access Key ID */}
              <div>
                <div className="flex justify-between items-center mb-1">
                  <label className="text-xs font-medium text-ink-secondary">
                    Access Key ID
                  </label>
                  <span className="text-[10px] text-ink-tertiary font-mono">
                    Pattern: AKIA/ASIA + 16 chars
                  </span>
                </div>
                <input
                  type="text"
                  placeholder="AKIA****************"
                  value={accessKeyId}
                  onChange={(e) => setAccessKeyId(e.target.value.toUpperCase())}
                  className={`w-full bg-canvas border rounded-md px-3 py-1.5 text-xs text-ink-primary font-mono focus:outline-hidden ${
                    accessKeyError ? 'border-rose-500 focus:border-rose-500' : 'border-line focus:border-brand'
                  }`}
                />
                {accessKeyError && (
                  <p className="text-[11px] text-rose-400 mt-1 flex items-center gap-1">
                    <XCircle className="h-3 w-3 inline shrink-0" />
                    {accessKeyError}
                  </p>
                )}
              </div>

              {/* Secret Access Key */}
              <div>
                <div className="flex justify-between items-center mb-1">
                  <label className="text-xs font-medium text-ink-secondary">
                    Secret Access Key
                  </label>
                  <span className="text-[10px] text-ink-tertiary">
                    {isEdit ? 'Leave blank to keep existing' : 'Exactly 40 chars'}
                  </span>
                </div>
                <div className="relative">
                  <input
                    type={showSecret ? 'text' : 'password'}
                    placeholder={isEdit ? '•••••••••••••••••••• (unchanged)' : '••••••••••••••••••••'}
                    value={secretAccessKey}
                    onChange={(e) => setSecretAccessKey(e.target.value)}
                    className={`w-full bg-canvas border rounded-md pl-3 pr-9 py-1.5 text-xs text-ink-primary font-mono focus:outline-hidden ${
                      secretError ? 'border-rose-500 focus:border-rose-500' : 'border-line focus:border-brand'
                    }`}
                  />
                  <button
                    type="button"
                    onClick={() => setShowSecret(!showSecret)}
                    className="absolute right-2.5 top-2 text-ink-tertiary hover:text-ink-primary cursor-pointer"
                  >
                    {showSecret ? <EyeOff className="h-3.5 w-3.5" /> : <Eye className="h-3.5 w-3.5" />}
                  </button>
                </div>
                {secretError && (
                  <p className="text-[11px] text-rose-400 mt-1 flex items-center gap-1">
                    <XCircle className="h-3 w-3 inline shrink-0" />
                    {secretError}
                  </p>
                )}
              </div>
            </div>
          ) : (
            <div>
              <label className="block text-xs font-medium text-ink-secondary mb-1.5">
                Profile Name
              </label>
              <input
                type="text"
                value={profileName}
                onChange={(e) => setProfileName(e.target.value)}
                placeholder="default"
                className="w-full bg-canvas border border-line rounded-md px-3 py-1.5 text-xs text-ink-primary font-mono focus:outline-hidden focus:border-brand"
              />
            </div>
          )}

          {/* Region */}
          <div>
            <label className="block text-xs font-medium text-ink-secondary mb-1.5">
              Default Region
            </label>
            <select
              value={region}
              onChange={(e) => setRegion(e.target.value)}
              className="w-full bg-canvas border border-line rounded-md px-3 py-1.5 text-xs text-ink-primary focus:outline-hidden focus:border-brand font-mono"
            >
              {REGIONS.map((r) => (
                <option key={r} value={r}>
                  {r}
                </option>
              ))}
            </select>
          </div>

          {/* SERVICES Scope */}
          <div>
            <div className="flex items-center justify-between mb-2">
              <div>
                <label className="text-xs font-medium text-ink-primary flex items-center gap-1.5">
                  <Shield className="h-3.5 w-3.5 text-brand" />
                  Services (Scope)
                </label>
                <p className="text-[11px] text-ink-tertiary">
                  Allowed scope: Vellum rejects plan/execute outside selected services
                </p>
              </div>

              {/* Presets */}
              <div className="flex items-center gap-1">
                <button
                  type="button"
                  onClick={() => setServices(PRESETS.recommended)}
                  className="text-[10px] px-1.5 py-0.5 rounded bg-elevated hover:bg-line text-ink-secondary cursor-pointer"
                >
                  Recommended
                </button>
                <button
                  type="button"
                  onClick={() => setServices(PRESETS.all)}
                  className="text-[10px] px-1.5 py-0.5 rounded bg-elevated hover:bg-line text-ink-secondary cursor-pointer"
                >
                  All
                </button>
                <button
                  type="button"
                  onClick={() => setServices(PRESETS.storage)}
                  className="text-[10px] px-1.5 py-0.5 rounded bg-elevated hover:bg-line text-ink-secondary cursor-pointer"
                >
                  Storage-only
                </button>
              </div>
            </div>

            {/* Service Toggle Chips */}
            <div className="flex flex-wrap gap-1.5">
              {ALL_SERVICES.map((svc) => {
                const active = services.includes(svc);
                return (
                  <button
                    key={svc}
                    type="button"
                    onClick={() => toggleService(svc)}
                    className={`px-2.5 py-1 text-xs rounded-md border font-mono flex items-center gap-1 transition-all cursor-pointer ${
                      active
                        ? 'bg-brand/10 border-brand/40 text-brand font-semibold shadow-xs'
                        : 'bg-canvas border-line text-ink-tertiary hover:text-ink-secondary'
                    }`}
                  >
                    <span>{svc}</span>
                    {active ? <Check className="h-3 w-3" /> : <X className="h-3 w-3 text-ink-tertiary" />}
                  </button>
                );
              })}
            </div>
          </div>

          {/* Test Connection Section */}
          <div className="p-3.5 bg-canvas rounded-lg border border-line space-y-3">
            <div className="flex items-center justify-between">
              <div>
                <span className="text-xs font-semibold text-ink-primary">Live Connection Probe</span>
                <p className="text-[11px] text-ink-tertiary">
                  Verifies STS identity & tests read-only permission per selected service
                </p>
              </div>
              <Button
                type="button"
                variant="outline"
                size="sm"
                loading={isTesting}
                disabled={!canTest || isTesting}
                onClick={handleRunTest}
                leftIcon={<Play className="h-3 w-3" />}
              >
                Test Connection
              </Button>
            </div>

            {testError && (
              <div className="p-2 bg-rose-500/10 border border-rose-500/30 rounded text-xs text-rose-400 flex items-center gap-2">
                <XCircle className="h-4 w-4 shrink-0" />
                <span>{testError}</span>
              </div>
            )}

            {testResult && (
              <div className="space-y-2 pt-2 border-t border-line text-xs">
                <div className="flex items-center justify-between text-ink-secondary">
                  <span>STS Account ID:</span>
                  <span className="font-mono text-ink-primary">{testResult.account_id || 'Unverified'}</span>
                </div>
                <div className="flex items-center justify-between text-ink-secondary">
                  <span>Caller ARN:</span>
                  <span className="font-mono text-ink-primary truncate max-w-[280px]" title={testResult.arn || 'Unverified'}>
                    {testResult.arn || 'Unverified'}
                  </span>
                </div>

                <div className="pt-2">
                  <span className="text-[11px] font-semibold text-ink-tertiary uppercase tracking-wider block mb-1">
                    Service Probes ({testResult.services.length})
                  </span>
                  <div className="space-y-1 max-h-36 overflow-y-auto">
                    {testResult.services.map((p) => {
                      const isOk = p.status === 'ok';
                      return (
                        <div
                          key={p.service}
                          className="flex items-center justify-between p-1.5 rounded bg-surface border border-line"
                        >
                          <div className="flex items-center gap-2">
                            {isOk ? (
                              <CheckCircle2 className="h-3.5 w-3.5 text-emerald-400" />
                            ) : (
                              <XCircle className="h-3.5 w-3.5 text-rose-400" />
                            )}
                            <span className="font-mono font-medium text-ink-primary">{p.service}</span>
                            {!isOk && p.error && (
                              <span className="text-[10px] text-rose-400 truncate max-w-[160px]" title={p.error}>
                                {p.error}
                              </span>
                            )}
                          </div>
                          <div className="flex items-center gap-2">
                            <span className="text-[10px] font-mono text-ink-tertiary">{p.latency_ms}ms</span>
                            {!isOk && services.includes(p.service) && (
                              <button
                                type="button"
                                onClick={() => toggleService(p.service)}
                                className="text-[10px] px-1.5 py-0.5 rounded bg-rose-500/10 text-rose-400 hover:bg-rose-500/20 cursor-pointer"
                              >
                                Deselect
                              </button>
                            )}
                          </div>
                        </div>
                      );
                    })}
                  </div>
                </div>
              </div>
            )}
          </div>
        </form>

        {/* Footer Actions */}
        <div className="p-4 border-t border-line flex items-center justify-between bg-surface">
          <Button type="button" variant="outline" size="sm" onClick={onClose}>
            Cancel
          </Button>

          <Button
            type="button"
            variant="primary"
            size="sm"
            loading={saving}
            disabled={!canSave}
            onClick={handleSave}
            leftIcon={<Save className="h-3.5 w-3.5" />}
          >
            Save Connection
          </Button>
        </div>
      </div>
    </div>
  );
};
