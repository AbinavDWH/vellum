import React, { useEffect, useState, useRef } from 'react';
import {
  PanelLeft,
  Search,
  Layers,
  Server,
  Cpu,
  Radio,
  Sun,
  Moon,
  ChevronDown,
  Check,
  Key,
  ExternalLink,
  Sliders,
  Zap,
} from 'lucide-react';
import { Tooltip } from '../ui/Tooltip';
import { api } from '../../services/api';
import { cn } from '../../lib/utils';
import { useTheme } from '../../context/ThemeContext';
import { NavView } from './Sidebar';
import { Connection } from '../../types';

export interface TopbarProps {
  onToggleSidebar: () => void;
  onOpenCommandPalette: () => void;
  sidebarCollapsed: boolean;
  wsConnected?: boolean;
  onSelectView?: (view: NavView) => void;
  currentProvider?: string;
  currentEnvironment?: string;
  onTargetChange?: (provider: string, environment: string) => void;
}

const TARGET_PRESETS = [
  {
    provider: 'aws',
    environment: 'local',
    name: 'AWS (LocalStack)',
    description: 'Local containerized AWS mock (Fast & isolated)',
    badge: 'LOCAL',
    badgeColor: 'text-brand bg-brand/10 border-brand/20',
  },
  {
    provider: 'aws',
    environment: 'staging',
    name: 'AWS (Staging)',
    description: 'Cloud staging sandbox environment',
    badge: 'STAGING',
    badgeColor: 'text-sky-400 bg-sky-500/10 border-sky-500/30',
  },
  {
    provider: 'aws',
    environment: 'prod',
    name: 'AWS (Production)',
    description: 'Live cloud infrastructure (Critical scope)',
    badge: 'PROD',
    badgeColor: 'text-rose-400 bg-rose-500/10 border-rose-500/30',
  },
  {
    provider: 'gcp',
    environment: 'local',
    name: 'Google Cloud (GCP)',
    description: 'Google Cloud Platform simulation',
    badge: 'GCP',
    badgeColor: 'text-amber-400 bg-amber-500/10 border-amber-500/30',
  },
  {
    provider: 'azure',
    environment: 'local',
    name: 'Microsoft Azure',
    description: 'Azure Resource Manager simulation',
    badge: 'AZURE',
    badgeColor: 'text-indigo-400 bg-indigo-500/10 border-indigo-500/30',
  },
];

export const Topbar: React.FC<TopbarProps> = ({
  onToggleSidebar,
  onOpenCommandPalette,
  sidebarCollapsed,
  wsConnected = false,
  onSelectView,
  currentProvider,
  currentEnvironment,
  onTargetChange,
}) => {
  const { theme, toggleTheme } = useTheme();
  const [llmOnline, setLlmOnline] = useState(false);
  const [groqOnline, setGroqOnline] = useState(false);
  const [localLlmOnline, setLocalLlmOnline] = useState(false);
  const [activeProvider, setActiveProvider] = useState<string>('hybrid');
  const [activeModel, setActiveModel] = useState('Detecting...');
  const [targetCloud, setTargetCloud] = useState('AWS (LocalStack)');
  const [latencyMs, setLatencyMs] = useState<number | null>(null);
  const [connections, setConnections] = useState<Connection[]>([]);
  const [isTargetMenuOpen, setIsTargetMenuOpen] = useState(false);
  const [targetTab, setTargetTab] = useState<'presets' | 'connections'>('presets');
  const [isAiMenuOpen, setIsAiMenuOpen] = useState(false);

  const targetMenuRef = useRef<HTMLDivElement>(null);
  const aiMenuRef = useRef<HTMLDivElement>(null);
  const closeTimeoutRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  // Effective target cloud provider & environment
  const effectiveProvider = currentProvider || 'aws';
  const effectiveEnvironment = currentEnvironment || 'local';
  const activePreset = TARGET_PRESETS.find(
    (p) => p.provider === effectiveProvider && p.environment === effectiveEnvironment
  );
  const displayTargetCloud = activePreset
    ? activePreset.name
    : `${effectiveProvider.toUpperCase()} (${effectiveEnvironment})`;

  // Sync targetCloud if parent passes currentProvider/currentEnvironment
  useEffect(() => {
    if (currentProvider && currentEnvironment) {
      setTargetCloud(displayTargetCloud);
    }
  }, [currentProvider, currentEnvironment, displayTargetCloud]);

  // Poll system health and connections every 15s
  useEffect(() => {
    let isMounted = true;

    const pollHealth = async () => {
      const startTime = performance.now();
      try {
        const [data, conns] = await Promise.all([
          api.getHealth(),
          api.getConnections().catch(() => []),
        ]);
        const duration = Math.round(performance.now() - startTime);
        if (!isMounted) return;
        setLatencyMs(duration);
        setLlmOnline(Boolean(data.active_online !== undefined ? data.active_online : (data.groq_online || data.lm_studio_online)));
        setGroqOnline(Boolean(data.groq_online));
        setLocalLlmOnline(Boolean(data.lm_studio_online));
        setActiveProvider(data.active_provider || 'groq');
        setActiveModel(data.active_model || 'Groq');
        // Only update targetCloud fallback if parent does not provide currentProvider / currentEnvironment
        if (!currentProvider && !currentEnvironment && data.cloud_provider) {
          setTargetCloud(`${data.cloud_provider.toUpperCase()} (${data.cloud_env || 'LocalStack'})`);
        }
        setConnections(conns);
      } catch {
        if (!isMounted) return;
        setLatencyMs(null);
        setLlmOnline(false);
        setGroqOnline(false);
        setLocalLlmOnline(false);
        setActiveModel('offline');
      }
    };

    pollHealth();
    const interval = setInterval(pollHealth, 15000);
    return () => {
      isMounted = false;
      clearInterval(interval);
    };
  }, []);

  // Hover handlers with debounce to prevent flicker when moving cursor down
  const handleMouseEnter = () => {
    if (closeTimeoutRef.current) {
      clearTimeout(closeTimeoutRef.current);
      closeTimeoutRef.current = null;
    }
    setIsTargetMenuOpen(true);
  };

  const handleMouseLeave = () => {
    if (closeTimeoutRef.current) {
      clearTimeout(closeTimeoutRef.current);
    }
    closeTimeoutRef.current = setTimeout(() => {
      setIsTargetMenuOpen(false);
    }, 200);
  };

  // Close on outside click or Escape key
  useEffect(() => {
    const handleClickOutside = (e: MouseEvent) => {
      if (targetMenuRef.current && !targetMenuRef.current.contains(e.target as Node)) {
        setIsTargetMenuOpen(false);
      }
      if (aiMenuRef.current && !aiMenuRef.current.contains(e.target as Node)) {
        setIsAiMenuOpen(false);
      }
    };
    const handleKeyDown = (e: KeyboardEvent) => {
      if (e.key === 'Escape') {
        setIsTargetMenuOpen(false);
        setIsAiMenuOpen(false);
      }
    };
    document.addEventListener('mousedown', handleClickOutside);
    document.addEventListener('keydown', handleKeyDown);
    return () => {
      document.removeEventListener('mousedown', handleClickOutside);
      document.removeEventListener('keydown', handleKeyDown);
      if (closeTimeoutRef.current) {
        clearTimeout(closeTimeoutRef.current);
      }
    };
  }, []);

  const handleSwitchAiProvider = async (provider: 'groq' | 'local', model?: string) => {
    try {
      const res = await api.setActiveAI(provider, model);
      setActiveProvider(res.active_provider);
      setActiveModel(res.active_model);
      setLlmOnline(Boolean(res.active_online));
      setIsAiMenuOpen(false);
    } catch (e: any) {
      console.error('Failed to switch AI provider', e);
    }
  };

  const handleSelectPreset = (preset: typeof TARGET_PRESETS[0]) => {
    setTargetCloud(preset.name);
    onTargetChange?.(preset.provider, preset.environment);
    setIsTargetMenuOpen(false);
  };

  const handleSelectConnection = (conn: Connection) => {
    setTargetCloud(`${conn.name} (${conn.environment})`);
    onTargetChange?.(conn.provider, conn.environment);
    setIsTargetMenuOpen(false);
  };

  return (
    <header
      style={{ backgroundColor: 'var(--bg-surface)' }}
      className="h-14 border-b border-line px-4 flex items-center justify-between sticky top-0 z-40"
    >
      {/* Left: Sidebar toggle + Brand */}
      <div className="flex items-center gap-3">
        <button
          onClick={onToggleSidebar}
          aria-label={sidebarCollapsed ? 'Expand sidebar' : 'Collapse sidebar'}
          className="p-1.5 rounded-lg text-ink-secondary hover:text-ink-primary hover:bg-elevated transition-colors cursor-pointer focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand"
        >
          <PanelLeft className="h-4 w-4" aria-hidden="true" />
        </button>

        <div className="flex items-center gap-2.5">
          <div className="h-7 w-7 rounded-lg bg-brand/10 border border-brand/30 flex items-center justify-center text-brand-text">
            <Layers className="h-4 w-4" aria-hidden="true" />
          </div>
          <div className="flex items-center gap-2">
            <span className="font-bold text-sm tracking-tight text-ink-primary">
              VELLUM
            </span>
            <span className="text-[10px] font-mono px-1.5 py-0.2 rounded bg-brand/10 text-brand-text border border-brand/20">
              v1.0
            </span>
          </div>
        </div>
      </div>

      {/* Center: Command Palette Trigger (⌘K) */}
      <div className="flex-1 max-w-md mx-4">
        <button
          onClick={onOpenCommandPalette}
          className="w-full flex items-center justify-between px-3 py-1.5 text-xs text-ink-secondary bg-elevated/70 hover:bg-elevated border border-line hover:border-line/80 rounded-lg transition-colors cursor-pointer group focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand"
        >
          <div className="flex items-center gap-2 truncate">
            <Search className="h-3.5 w-3.5 text-ink-tertiary group-hover:text-ink-secondary" aria-hidden="true" />
            <span className="truncate">Search commands, plans, presets...</span>
          </div>
          <div className="flex items-center gap-1 shrink-0 ml-2">
            <kbd className="px-1.5 py-0.5 text-[10px] font-mono bg-surface border border-line rounded text-ink-secondary">
              ⌘K
            </kbd>
          </div>
        </button>
      </div>

      {/* Right: Live System Status Pills */}
      <div className="flex items-center gap-2 shrink-0">
        {/* Single AI Mode Pill & Dropdown Switcher */}
        <div ref={aiMenuRef} className="relative inline-flex">
          <button
            type="button"
            onClick={() => setIsAiMenuOpen((prev) => !prev)}
            aria-expanded={isAiMenuOpen}
            aria-haspopup="true"
            aria-label="Active AI engine switcher"
            className={cn(
              'flex items-center gap-1.5 px-2.5 py-1 rounded-full border text-xs cursor-pointer transition-all duration-150 select-none focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand',
              isAiMenuOpen
                ? 'bg-elevated border-brand/50 shadow-sm ring-1 ring-brand/30'
                : 'bg-elevated border-line hover:border-line/80 hover:bg-elevated/90'
            )}
          >
            {activeProvider === 'groq' ? (
              <Zap className="h-3.5 w-3.5 text-brand shrink-0" aria-hidden="true" />
            ) : (
              <Cpu className="h-3.5 w-3.5 text-purple-400 shrink-0" aria-hidden="true" />
            )}
            <span className="text-ink-secondary hidden md:inline">AI:</span>
            <span className="font-semibold text-ink-primary max-w-[120px] truncate" title={activeModel}>
              {activeProvider === 'groq' ? 'Groq' : 'Local LM'}
            </span>
            <span
              className={cn(
                'h-2 w-2 rounded-full shrink-0',
                llmOnline ? 'bg-ok shadow-sm' : 'bg-crit'
              )}
              aria-label={llmOnline ? 'AI online' : 'AI offline'}
            />
            <ChevronDown
              className={cn(
                'h-3 w-3 text-ink-tertiary transition-transform duration-200 ml-0.5',
                isAiMenuOpen && 'rotate-180 text-ink-primary'
              )}
            />
          </button>

          {/* AI Switcher Menu */}
          {isAiMenuOpen && (
            <div
              role="menu"
              style={{ backgroundColor: 'var(--bg-surface)' }}
              className="absolute top-full right-0 mt-2 w-80 flex flex-col rounded-xl border border-line shadow-2xl z-50 text-left overflow-hidden animate-in fade-in slide-in-from-top-1 select-none"
            >
              {/* Header */}
              <div
                style={{ backgroundColor: 'var(--bg-surface)' }}
                className="flex items-center justify-between px-3.5 py-2.5 border-b border-line shrink-0"
              >
                <div className="flex items-center gap-2">
                  <div className="p-1.5 rounded-lg bg-brand/10 text-brand border border-brand/20">
                    <Cpu className="h-4 w-4" />
                  </div>
                  <div>
                    <div className="text-xs font-semibold text-ink-primary">Active AI Engine</div>
                    <div className="text-[10px] text-ink-tertiary">Single AI Mode (1 active at a time)</div>
                  </div>
                </div>
                <div className="flex items-center gap-1.5 px-2 py-0.5 rounded-full bg-ok/10 border border-ok/30 text-[10px] text-ok font-medium">
                  <span className="h-1.5 w-1.5 rounded-full bg-ok animate-pulse" />
                  Active
                </div>
              </div>

              {/* Providers list */}
              <div className="p-3 space-y-2.5">
                {/* Groq Cloud */}
                <button
                  type="button"
                  onClick={() => handleSwitchAiProvider('groq')}
                  className={cn(
                    'w-full p-2.5 rounded-lg border transition-all cursor-pointer text-left',
                    activeProvider === 'groq'
                      ? 'bg-brand/10 border-brand/60 shadow-xs ring-1 ring-brand/30'
                      : 'bg-elevated/40 border-line hover:border-line/80 hover:bg-elevated'
                  )}
                >
                  <div className="flex items-center justify-between mb-1">
                    <div className="flex items-center gap-2">
                      <Zap className="h-4 w-4 text-brand" />
                      <span className="text-xs font-semibold text-ink-primary">⚡ Groq Cloud AI</span>
                    </div>
                    <div className="flex items-center gap-1.5">
                      <span
                        className={cn(
                          'text-[10px] px-1.5 py-0.2 rounded font-medium',
                          groqOnline ? 'bg-ok/10 text-ok border border-ok/20' : 'bg-crit/10 text-crit border border-crit/20'
                        )}
                      >
                        {groqOnline ? 'Online (<1s)' : 'Offline'}
                      </span>
                      {activeProvider === 'groq' && <Check className="h-3.5 w-3.5 text-brand" />}
                    </div>
                  </div>
                  <p className="text-[11px] text-ink-secondary mb-1.5">
                    Cloud inference via Groq API. Ultra-fast response times for natural architectural conversations.
                  </p>
                  <div className="flex items-center gap-1.5 text-[10px] font-mono text-ink-tertiary">
                    <span className="px-1.5 py-0.2 rounded bg-surface border border-line">openai/gpt-oss-120b</span>
                  </div>
                </button>

                {/* Local LM Studio */}
                <button
                  type="button"
                  onClick={() => handleSwitchAiProvider('local')}
                  className={cn(
                    'w-full p-2.5 rounded-lg border transition-all cursor-pointer text-left',
                    activeProvider === 'local'
                      ? 'bg-brand/10 border-brand/60 shadow-xs ring-1 ring-brand/30'
                      : 'bg-elevated/40 border-line hover:border-line/80 hover:bg-elevated'
                  )}
                >
                  <div className="flex items-center justify-between mb-1">
                    <div className="flex items-center gap-2">
                      <Cpu className="h-4 w-4 text-purple-400" />
                      <span className="text-xs font-semibold text-ink-primary">🖥️ Local LM Studio</span>
                    </div>
                    <div className="flex items-center gap-1.5">
                      <span
                        className={cn(
                          'text-[10px] px-1.5 py-0.2 rounded font-medium',
                          localLlmOnline ? 'bg-ok/10 text-ok border border-ok/20' : 'bg-crit/10 text-crit border border-crit/20'
                        )}
                      >
                        {localLlmOnline ? 'Online (1234/v1)' : 'Offline'}
                      </span>
                      {activeProvider === 'local' && <Check className="h-3.5 w-3.5 text-brand" />}
                    </div>
                  </div>
                  <p className="text-[11px] text-ink-secondary mb-1.5">
                    Local, on-device AI running privately on your workstation without external cloud dependencies.
                  </p>
                  <div className="flex items-center gap-1.5 text-[10px] font-mono text-ink-tertiary">
                    <span className="px-1.5 py-0.2 rounded bg-surface border border-line">http://localhost:1234/v1</span>
                  </div>
                </button>
              </div>

              {/* Footer info */}
              <div
                style={{ backgroundColor: 'var(--bg-surface)' }}
                className="px-3 py-2 border-t border-line text-[10px] text-ink-tertiary flex items-center justify-between"
              >
                <span>Only 1 AI runs at a time • Zero fallback mixing</span>
                {latencyMs !== null && <span className="font-mono">{latencyMs}ms ping</span>}
              </div>
            </div>
          )}
        </div>

        {/* Target Cloud Status Pill with Downward Expansion Dropdown */}
        <div
          ref={targetMenuRef}
          className="relative hidden sm:inline-flex"
          onMouseEnter={handleMouseEnter}
          onMouseLeave={handleMouseLeave}
        >
          <button
            type="button"
            onClick={() => setIsTargetMenuOpen((prev) => !prev)}
            aria-expanded={isTargetMenuOpen}
            aria-haspopup="true"
            aria-label="Target cloud environment selector"
            className={cn(
              'flex items-center gap-1.5 px-2.5 py-1 rounded-full border text-xs cursor-pointer transition-all duration-150 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand select-none',
              isTargetMenuOpen
                ? 'bg-elevated border-brand/50 shadow-sm ring-1 ring-brand/30'
                : 'bg-elevated border-line hover:border-line/80 hover:bg-elevated/90'
            )}
          >
            <Server className="h-3.5 w-3.5 text-warn shrink-0" aria-hidden="true" />
            <span className="text-ink-secondary">Target:</span>
            <span className="font-semibold text-ink-primary truncate max-w-[130px]">{displayTargetCloud}</span>
            <span className="h-2 w-2 rounded-full bg-ok shrink-0 ml-0.5" aria-label="Target healthy" />
            <ChevronDown
              className={cn(
                'h-3 w-3 text-ink-tertiary transition-transform duration-200 ml-0.5',
                isTargetMenuOpen && 'rotate-180 text-ink-primary'
              )}
            />
          </button>

          {/* Downward Expansion Menu - Fully Opaque Solid Surface */}
          {isTargetMenuOpen && (
            <div
              role="menu"
              style={{ backgroundColor: 'var(--bg-surface)' }}
              className="absolute top-full right-0 mt-2 w-96 max-h-[min(520px,calc(100vh-80px))] flex flex-col rounded-xl border border-line shadow-2xl z-50 text-left overflow-hidden animate-in fade-in slide-in-from-top-1 select-none"
            >
              {/* Menu Header */}
              <div
                style={{ backgroundColor: 'var(--bg-surface)' }}
                className="flex items-center justify-between px-3.5 py-2.5 border-b border-line shrink-0"
              >
                <div className="flex items-center gap-2">
                  <div className="p-1.5 rounded-lg bg-warn/10 text-warn border border-warn/20">
                    <Server className="h-4 w-4" />
                  </div>
                  <div>
                    <div className="text-xs font-semibold text-ink-primary">Execution Target</div>
                    <div className="text-[10px] text-ink-tertiary">Select cloud environment or connection</div>
                  </div>
                </div>
                <div className="flex items-center gap-1.5 px-2 py-0.5 rounded-full bg-ok/10 border border-ok/30 text-[10px] text-ok font-medium">
                  <span className="h-1.5 w-1.5 rounded-full bg-ok animate-pulse" />
                  Active
                </div>
              </div>

              {/* Segmented Switcher: Presets vs Saved Connections */}
              <div
                style={{ backgroundColor: 'var(--bg-surface)' }}
                className="flex border-b border-line px-3 pt-1.5 gap-2 shrink-0"
              >
                <button
                  type="button"
                  onClick={() => setTargetTab('presets')}
                  className={cn(
                    'pb-2 px-1 text-xs font-medium border-b-2 transition-colors cursor-pointer',
                    targetTab === 'presets'
                      ? 'border-brand text-brand-text font-semibold'
                      : 'border-transparent text-ink-tertiary hover:text-ink-secondary'
                  )}
                >
                  Cloud Targets
                </button>
                {connections.length > 0 && (
                  <button
                    type="button"
                    onClick={() => setTargetTab('connections')}
                    className={cn(
                      'pb-2 px-1 text-xs font-medium border-b-2 transition-colors cursor-pointer flex items-center gap-1.5',
                      targetTab === 'connections'
                        ? 'border-brand text-brand-text font-semibold'
                        : 'border-transparent text-ink-tertiary hover:text-ink-secondary'
                    )}
                  >
                    <span>Configured Connections</span>
                    <span className="text-[10px] font-mono px-1.5 py-0.2 rounded-full bg-elevated border border-line text-ink-secondary">
                      {connections.length}
                    </span>
                  </button>
                )}
              </div>

              {/* Body: Scrollable list of items with solid background */}
              <div
                style={{ backgroundColor: 'var(--bg-surface)' }}
                className="flex-1 overflow-y-auto p-2 space-y-1 max-h-[280px]"
              >
                {targetTab === 'presets' && (
                  <>
                    {TARGET_PRESETS.map((preset) => {
                      const isCurrent =
                        preset.provider === effectiveProvider &&
                        preset.environment === effectiveEnvironment;
                      return (
                        <button
                          key={`${preset.provider}-${preset.environment}`}
                          type="button"
                          onClick={() => handleSelectPreset(preset)}
                          style={{
                            backgroundColor: isCurrent ? 'var(--brand-dim)' : undefined,
                          }}
                          className={cn(
                            'w-full flex items-center justify-between p-2 rounded-lg text-left transition-colors cursor-pointer group',
                            isCurrent
                              ? 'border border-brand/40 shadow-sm'
                              : 'hover:bg-elevated border border-transparent'
                          )}
                        >
                          <div className="flex items-center gap-2.5 min-w-0">
                            <div
                              className={cn(
                                'h-2 w-2 rounded-full shrink-0',
                                isCurrent ? 'bg-brand' : 'bg-ink-tertiary group-hover:bg-ink-secondary'
                              )}
                            />
                            <div className="truncate">
                              <div className="text-xs font-medium text-ink-primary flex items-center gap-1.5">
                                <span>{preset.name}</span>
                                <span className={cn('text-[9px] font-mono px-1.5 py-0.2 rounded border', preset.badgeColor)}>
                                  {preset.badge}
                                </span>
                              </div>
                              <div className="text-[10px] text-ink-tertiary truncate">
                                {preset.description}
                              </div>
                            </div>
                          </div>
                          {isCurrent && <Check className="h-4 w-4 text-brand shrink-0 ml-2" />}
                        </button>
                      );
                    })}
                  </>
                )}

                {targetTab === 'connections' && (
                  <>
                    {connections.map((conn) => {
                      const isCurrent = targetCloud.toLowerCase().includes(conn.name.toLowerCase());
                      const envBadgeColor =
                        conn.environment === 'prod'
                          ? 'text-rose-400 bg-rose-500/10 border-rose-500/30'
                          : conn.environment === 'staging'
                          ? 'text-sky-400 bg-sky-500/10 border-sky-500/30'
                          : 'text-brand bg-brand/10 border-brand/20';

                      return (
                        <button
                          key={conn.id}
                          type="button"
                          onClick={() => handleSelectConnection(conn)}
                          style={{
                            backgroundColor: isCurrent ? 'var(--brand-dim)' : undefined,
                          }}
                          className={cn(
                            'w-full flex items-center justify-between p-2 rounded-lg text-left transition-colors cursor-pointer group',
                            isCurrent
                              ? 'border border-brand/40 shadow-sm'
                              : 'hover:bg-elevated border border-transparent'
                          )}
                        >
                          <div className="flex items-center gap-2.5 min-w-0">
                            <span
                              className={cn(
                                'h-2 w-2 rounded-full shrink-0',
                                conn.status === 'connected' ? 'bg-ok' : 'bg-warn'
                              )}
                              title={conn.status === 'connected' ? 'Connected' : 'Untested / Warning'}
                            />
                            <div className="truncate">
                              <div className="text-xs font-medium text-ink-primary flex items-center gap-1.5">
                                <span className="truncate font-mono">{conn.name}</span>
                                <span className={cn('text-[9px] font-mono uppercase px-1.5 py-0.2 rounded border', envBadgeColor)}>
                                  {conn.environment}
                                </span>
                              </div>
                              <div className="text-[10px] text-ink-tertiary truncate">
                                {conn.provider.toUpperCase()} · {conn.services?.length || 0} services enabled
                              </div>
                            </div>
                          </div>
                          {isCurrent && <Check className="h-4 w-4 text-brand shrink-0 ml-2" />}
                        </button>
                      );
                    })}
                  </>
                )}
              </div>

              {/* Action Links Footer */}
              <div
                style={{ backgroundColor: 'var(--bg-surface)' }}
                className="p-2 border-t border-line space-y-1 shrink-0"
              >
                {onSelectView && (
                  <button
                    type="button"
                    onClick={() => {
                      setIsTargetMenuOpen(false);
                      onSelectView('connections');
                    }}
                    className="w-full flex items-center justify-between px-2.5 py-1.5 rounded-lg text-xs text-ink-secondary hover:text-ink-primary hover:bg-elevated transition-colors cursor-pointer group"
                  >
                    <div className="flex items-center gap-2 truncate">
                      <Key className="h-3.5 w-3.5 text-brand shrink-0" />
                      <span className="truncate font-medium">Manage Connections & Scopes</span>
                    </div>
                    <ExternalLink className="h-3 w-3 text-ink-tertiary group-hover:text-ink-secondary shrink-0" />
                  </button>
                )}
                {onSelectView && (
                  <button
                    type="button"
                    onClick={() => {
                      setIsTargetMenuOpen(false);
                      onSelectView('settings');
                    }}
                    className="w-full flex items-center justify-between px-2.5 py-1.5 rounded-lg text-xs text-ink-secondary hover:text-ink-primary hover:bg-elevated transition-colors cursor-pointer group"
                  >
                    <div className="flex items-center gap-2 truncate">
                      <Sliders className="h-3.5 w-3.5 text-ink-tertiary shrink-0" />
                      <span className="truncate">Control Plane Settings</span>
                    </div>
                    <ExternalLink className="h-3 w-3 text-ink-tertiary group-hover:text-ink-secondary shrink-0" />
                  </button>
                )}
              </div>
            </div>
          )}
        </div>

        {/* WebSocket Status Pill (Downward Tooltip) */}
        <Tooltip
          side="bottom"
          align="end"
          content={wsConnected ? 'Execution WebSocket Connected' : 'Execution WebSocket Standby'}
        >
          <div className="flex items-center gap-1.5 px-2 py-1 rounded-full bg-elevated border border-line text-xs">
            <Radio className="h-3.5 w-3.5 text-info shrink-0" aria-hidden="true" />
            <span className="text-ink-secondary hidden lg:inline">WS</span>
            <span
              className={cn(
                'h-2 w-2 rounded-full shrink-0',
                wsConnected ? 'bg-ok animate-pulse' : 'bg-ink-tertiary'
              )}
              aria-label={wsConnected ? 'WebSocket connected' : 'WebSocket standby'}
            />
          </div>
        </Tooltip>

        {/* Theme Switcher (Downward Tooltip) */}
        <Tooltip
          side="bottom"
          align="end"
          content={`Switch to ${theme === 'dark' ? 'Light' : 'Dark'} theme`}
        >
          <button
            type="button"
            onClick={toggleTheme}
            aria-label={`Switch to ${theme === 'dark' ? 'Light' : 'Dark'} theme`}
            className="p-1.5 rounded-lg text-ink-secondary hover:text-ink-primary hover:bg-elevated transition-colors cursor-pointer focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand ml-1"
          >
            {theme === 'dark' ? (
              <Sun className="h-4 w-4 text-brand" aria-hidden="true" />
            ) : (
              <Moon className="h-4 w-4 text-brand-text" aria-hidden="true" />
            )}
          </button>
        </Tooltip>
      </div>
    </header>
  );
};
