import React, { useState, useEffect, useCallback } from 'react';
import { Topbar } from './components/Shell/Topbar';
import { Sidebar, NavView } from './components/Shell/Sidebar';
import { Statusbar } from './components/Shell/Statusbar';
import { CommandPalette } from './components/Shell/CommandPalette';
import { DesignerScreen } from './components/Designer/DesignerScreen';
import { PlansView } from './components/Plans/PlansView';
import { ExecutionsView } from './components/Executions/ExecutionsView';
import { AuditLogViewer } from './components/AuditLog/AuditLogViewer';
import { ConnectionsView } from './components/Connections/ConnectionsView';
import { SettingsView } from './components/Settings/SettingsView';
import { ExecutionConsole } from './components/ExecutionProgress/ExecutionConsole';
import { ChatMessage } from './components/Designer/ChatPane';
import { SessionDrawer } from './components/Designer/SessionDrawer';
import { PlanResponse, ChatSession } from './types';
import { api } from './services/api';
import { useToast } from './components/ui/Toast';
import { formatRelativeTime } from './lib/utils';

export const App: React.FC = () => {
  const { toast } = useToast();

  const getViewFromUrl = (): NavView => {
    try {
      const hash = window.location.hash.replace('#', '').replace(/^\//, '').split('?')[0];
      const validViews: NavView[] = ['designer', 'plans', 'executions', 'audit', 'connections', 'settings'];
      if (validViews.includes(hash as NavView)) {
        return hash as NavView;
      }
      const params = new URLSearchParams(window.location.search);
      const viewParam = params.get('view');
      if (viewParam && validViews.includes(viewParam as NavView)) {
        return viewParam as NavView;
      }
    } catch {}
    return 'designer';
  };

  // Navigation & Shell state
  const [activeView, setActiveView] = useState<NavView>(getViewFromUrl);
  const [sidebarCollapsed, setSidebarCollapsed] = useState<boolean>(() => {
    try {
      const params = new URLSearchParams(window.location.search);
      if (params.get('collapsed') === 'true') return true;
      const stored = localStorage.getItem('vellum_sidebar_collapsed');
      if (stored !== null) return stored === 'true';
      if (typeof window !== 'undefined' && window.innerWidth < 1280) return true;
      return false;
    } catch {
      return false;
    }
  });
  const [commandPaletteOpen, setCommandPaletteOpen] = useState(false);

  const changeView = (v: NavView) => {
    setActiveView(v);
    try {
      window.location.hash = `/${v}`;
    } catch {}
  };

  useEffect(() => {
    const onHashChange = () => {
      setActiveView(getViewFromUrl());
      try {
        const hashQuery = window.location.hash.includes('?') ? window.location.hash.split('?')[1] : '';
        const hashParams = new URLSearchParams(hashQuery);
        const planParam = hashParams.get('plan') || hashParams.get('executing');
        setExecutingPlanId(planParam || null);
      } catch {}
    };
    window.addEventListener('hashchange', onHashChange);
    return () => window.removeEventListener('hashchange', onHashChange);
  }, []);

  // M-13 Sessions & History state
  const [sessions, setSessions] = useState<ChatSession[]>([]);
  const [currentSessionId, setCurrentSessionId] = useState<string | null>(null);
  const [currentSessionTitle, setCurrentSessionTitle] = useState<string>('New Infrastructure Session');
  const [sessionDrawerOpen, setSessionDrawerOpen] = useState(false);
  const [driftDiff, setDriftDiff] = useState<{
    missing?: string[];
    verified?: number;
    expected?: string[];
    found?: string[];
  } | null>(null);

  // Chat & Plan Designer state
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [loading, setLoading] = useState(false);
  const [currentPlan, setCurrentPlan] = useState<PlanResponse | null>(null);
  const [executingPlanId, setExecutingPlanId] = useState<string | null>(() => {
    try {
      const searchParams = new URLSearchParams(window.location.search);
      const hashQuery = window.location.hash.includes('?') ? window.location.hash.split('?')[1] : '';
      const hashParams = new URLSearchParams(hashQuery);
      return searchParams.get('executing') || searchParams.get('plan') || hashParams.get('executing') || hashParams.get('plan') || null;
    } catch {
      return null;
    }
  });
  const [recentPlanIds, setRecentPlanIds] = useState<string[]>([]);
  const [lastVerifyTime, setLastVerifyTime] = useState<string | null>(null);

  // Target cloud provider and environment state (persisted in localStorage)
  const [targetProvider, setTargetProvider] = useState<string>(() => {
    try {
      return localStorage.getItem('vellum_target_provider') || 'aws';
    } catch {
      return 'aws';
    }
  });
  const [targetEnvironment, setTargetEnvironment] = useState<string>(() => {
    try {
      return localStorage.getItem('vellum_target_environment') || 'local';
    } catch {
      return 'local';
    }
  });
  const [currentRequirementsMd, setCurrentRequirementsMd] = useState<string>('');

  const handleTargetChange = (provider: string, env: string) => {
    setTargetProvider(provider);
    setTargetEnvironment(env);
    try {
      localStorage.setItem('vellum_target_provider', provider);
      localStorage.setItem('vellum_target_environment', env);
    } catch {}

    // Immediately synchronize the active session's requirements.md if present
    if (currentSessionId && currentRequirementsMd) {
      let updatedMd = currentRequirementsMd;
      updatedMd = updatedMd.replace(/(\*\*Environment\*\*:\s*)[a-zA-Z0-9_-]+/gi, `$1${env}`);
      updatedMd = updatedMd.replace(/(\*\*Cloud Provider\*\*:\s*)[a-zA-Z0-9_-]+/gi, `$1${provider.toUpperCase()}`);
      if (updatedMd !== currentRequirementsMd) {
        setCurrentRequirementsMd(updatedMd);
        api.updateSessionRequirements(currentSessionId, updatedMd).catch((err) => {
          console.warn('Failed to persist target update to session requirements', err);
        });
      }
    }

    toast({
      title: 'Target Environment Updated',
      description: `Target set to ${provider.toUpperCase()} (${env}). Subsequent prompts will target this environment.`,
      type: 'info',
    });
  };

  // Toggle and persist sidebar collapse
  const handleToggleSidebar = () => {
    setSidebarCollapsed((prev) => {
      const next = !prev;
      try {
        localStorage.setItem('vellum_sidebar_collapsed', String(next));
      } catch {}
      return next;
    });
  };

  // Keyboard shortcut listener for ⌘K / Ctrl+K
  useEffect(() => {
    const handleKeyDown = (e: KeyboardEvent) => {
      if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === 'k') {
        e.preventDefault();
        setCommandPaletteOpen((prev) => !prev);
      }
    };
    window.addEventListener('keydown', handleKeyDown);
    return () => window.removeEventListener('keydown', handleKeyDown);
  }, []);

  // Load Sessions (M-13)
  const loadSessions = useCallback(async (search?: string) => {
    try {
      const list = await api.getSessions(search);
      setSessions(list);
      return list;
    } catch (err) {
      console.warn('Failed to load sessions', err);
      return [];
    }
  }, []);

  const handleSelectSession = async (sessionId: string, shouldNavigate = true) => {
    setLoading(true);
    setCurrentSessionId(sessionId);
    setDriftDiff(null);
    try {
      const sessionData = await api.getSession(sessionId);
      setCurrentSessionTitle(sessionData.title);
      const syncEnvFromMd = (mdText: string) => {
        if (!mdText) return;
        const envMatch = mdText.match(/\*\*Environment\*\*:\s*([a-zA-Z0-9_-]+)/i);
        const provMatch = mdText.match(/\*\*Cloud Provider\*\*:\s*([a-zA-Z0-9_-]+)/i);
        const isDefaultTemplate = mdText.includes('*No requirements documented yet');

        if (envMatch && envMatch[1]) {
          const loadedEnv = envMatch[1].trim().toLowerCase();
          if (loadedEnv === 'prod' || loadedEnv === 'staging') {
            setTargetEnvironment(loadedEnv);
            try { localStorage.setItem('vellum_target_environment', loadedEnv); } catch {}
          } else if (targetEnvironment === 'prod' && isDefaultTemplate) {
            const upgradedMd = mdText.replace(/(\*\*Environment\*\*:\s*)[a-zA-Z0-9_-]+/gi, `$1${targetEnvironment}`);
            api.updateSessionRequirements(sessionId, upgradedMd).catch(() => {});
          } else if (loadedEnv === 'local' && targetEnvironment !== 'prod') {
            setTargetEnvironment('local');
            try { localStorage.setItem('vellum_target_environment', 'local'); } catch {}
          }
        }
        if (provMatch && provMatch[1]) {
          const loadedProv = provMatch[1].trim().toLowerCase();
          setTargetProvider(loadedProv);
          try { localStorage.setItem('vellum_target_provider', loadedProv); } catch {}
        }
      };

      if (sessionData.requirements_md) {
        setCurrentRequirementsMd(sessionData.requirements_md);
        syncEnvFromMd(sessionData.requirements_md);
      } else {
        api.getSessionRequirements(sessionId)
          .then((r) => {
            setCurrentRequirementsMd(r.requirements_md);
            syncEnvFromMd(r.requirements_md);
          })
          .catch(() => setCurrentRequirementsMd(''));
      }

      if (sessionData.last_plan) {
        setCurrentPlan(sessionData.last_plan);
      } else if (sessionData.last_plan_id) {
        api.getPlan(sessionData.last_plan_id).then(setCurrentPlan).catch(() => {});
      } else {
        setCurrentPlan(null);
      }

      const msgs = await api.getSessionMessages(sessionId);
      const formatted: ChatMessage[] = msgs.map((m) => ({
        id: m.id,
        sender: m.role === 'assistant' ? 'assistant' : 'user',
        text: m.content,
        timestamp: m.created_at || new Date().toISOString(),
        clarification: m.clarification || undefined,
      }));
      setMessages(formatted);
      if (shouldNavigate) {
        changeView('designer');
      }
    } catch (err: any) {
      toast({
        title: 'Error loading conversation',
        description: err.message || 'Could not restore conversation thread',
        type: 'crit',
      });
    } finally {
      setLoading(false);
    }
  };

  const handleNewChat = (shouldNavigate = true) => {
    const newId = `sess_${Date.now().toString(36)}_${Math.random().toString(36).substring(2, 6)}`;
    setCurrentSessionId(newId);
    setCurrentSessionTitle('New Infrastructure Session');
    setCurrentRequirementsMd('');
    setMessages([]);
    setCurrentPlan(null);
    setDriftDiff(null);
    api.createSession('New Infrastructure Session', targetProvider, targetEnvironment)
      .then((sess) => {
        if (sess.requirements_md) {
          setCurrentRequirementsMd(sess.requirements_md);
        }
      })
      .catch(() => {});
    if (shouldNavigate) {
      changeView('designer');
    }
  };

  const handleRenameSession = async (sessionId: string, newTitle: string) => {
    try {
      await api.renameSession(sessionId, newTitle);
      if (currentSessionId === sessionId) {
        setCurrentSessionTitle(newTitle);
      }
      await loadSessions();
      toast({
        title: 'Session Renamed',
        description: `Renamed to "${newTitle}".`,
        type: 'success',
      });
    } catch (err: any) {
      toast({
        title: 'Rename Failed',
        description: err.message || 'Failed to rename session',
        type: 'crit',
      });
    }
  };

  const handleDeleteSession = async (sessionId: string) => {
    try {
      await api.deleteSession(sessionId);
      toast({
        title: 'Session Deleted',
        description: 'Session removed. Audit trail preserved.',
        type: 'info',
      });
      const remaining = await loadSessions();
      if (currentSessionId === sessionId) {
        if (remaining.length > 0) {
          handleSelectSession(remaining[0].id);
        } else {
          handleNewChat();
        }
      }
    } catch (err: any) {
      toast({
        title: 'Delete Failed',
        description: err.message || 'Failed to delete session',
        type: 'crit',
      });
    }
  };

  // Fetch recent plans and sessions on start
  const refreshRecentPlans = async () => {
    try {
      const plans = await api.getPlans(20);
      setRecentPlanIds(plans.map((p) => p.plan_id));
      if (plans.length > 0 && !currentPlan) {
        // Pre-load latest plan details
        api.getPlan(plans[0].plan_id)
          .then((p) => setCurrentPlan(p))
          .catch(() => {});
      }
    } catch (err) {
      console.warn('Failed to load recent plans', err);
    }
  };

  useEffect(() => {
    refreshRecentPlans();
    loadSessions().then((list) => {
      if (list && list.length > 0) {
        handleSelectSession(list[0].id, false);
      } else {
        handleNewChat(false);
      }
    });
  }, []);

  // Clear chat history handler
  const handleClearHistory = async () => {
    try {
      if (currentSessionId) {
        await api.clearChatHistory(currentSessionId);
      } else {
        await api.clearChatHistory();
      }
      setMessages([]);
      toast({
        title: 'Chat History Cleared',
        description: 'All past conversation memory in this session wiped.',
        type: 'info',
      });
    } catch (err: any) {
      toast({
        title: 'Error',
        description: err.message || 'Failed to clear chat history',
        type: 'crit',
      });
    }
  };

  // Chat submission handler with write-through session ID
  const handleSendMessage = async (prompt: string) => {
    setLoading(true);
    const activeSessionId = currentSessionId || `sess_${Date.now().toString(36)}`;
    if (!currentSessionId) {
      setCurrentSessionId(activeSessionId);
    }

    const userMsg: ChatMessage = {
      id: Math.random().toString(36).substring(2, 9),
      sender: 'user',
      text: prompt,
      timestamp: new Date().toISOString(),
    };
    setMessages((prev) => [...prev, userMsg]);

    try {
      const response = await api.sendChat(prompt, activeSessionId, undefined, targetProvider, targetEnvironment);

      if (response.requirements_md) {
        setCurrentRequirementsMd(response.requirements_md);
      }

      if (response.status === 'conversation') {
        const assistantMsg: ChatMessage = {
          id: Math.random().toString(36).substring(2, 9),
          sender: 'assistant',
          text: response.message || '',
          timestamp: new Date().toISOString(),
          requirements_md: response.requirements_md,
          clarification: response.clarification,
        };
        setMessages((prev) => [...prev, assistantMsg]);
      } else if (response.status === 'clarification_needed' && response.clarification) {
        const assistantMsg: ChatMessage = {
          id: Math.random().toString(36).substring(2, 9),
          sender: 'assistant',
          text: response.message || 'I need a few clarifications to design an optimal infrastructure architecture.',
          timestamp: new Date().toISOString(),
          clarification: response.clarification,
        };
        setMessages((prev) => [...prev, assistantMsg]);
      } else if (response.status === 'plan_ready' && response.plan) {
        setCurrentPlan(response.plan);
        setDriftDiff(null);
        const assistantMsg: ChatMessage = {
          id: Math.random().toString(36).substring(2, 9),
          sender: 'assistant',
          text: `Plan generated: ${response.plan.plan_id} (${response.plan.intent.replace(/_/g, ' ')}). Review the topology, schema, code, and security checks in the workspace pane.`,
          timestamp: new Date().toISOString(),
          rag_citations: response.rag_citations,
          requirements_md: response.requirements_md,
        };
        setMessages((prev) => [...prev, assistantMsg]);
        refreshRecentPlans();
        toast({
          title: 'Plan Synthesized',
          description: `Plan ${response.plan.plan_id} is ready for human approval.`,
          type: 'success',
        });
      } else if (response.status === 'error') {
        const assistantMsg: ChatMessage = {
          id: Math.random().toString(36).substring(2, 9),
          sender: 'assistant',
          text: `Error: ${response.message}`,
          timestamp: new Date().toISOString(),
        };
        setMessages((prev) => [...prev, assistantMsg]);
        toast({
          title: 'Generation Failed',
          description: response.message,
          type: 'crit',
        });
      }

      // Refresh sessions to update auto-title and message counts
      const updatedSessions = await loadSessions();
      const current = updatedSessions.find((s) => s.id === activeSessionId);
      if (current) {
        setCurrentSessionTitle(current.title);
      }
    } catch (err: any) {
      const errText = err.message || 'Failed to process infrastructure requirement';
      const assistantMsg: ChatMessage = {
        id: Math.random().toString(36).substring(2, 9),
        sender: 'assistant',
        text: `Error: ${errText}`,
        timestamp: new Date().toISOString(),
      };
      setMessages((prev) => [...prev, assistantMsg]);
      toast({
        title: 'Inference Error',
        description: errText,
        type: 'crit',
      });
    } finally {
      setLoading(false);
    }
  };

  // Chat cancellation handler (M-20 / F8)
  const handleCancelChat = async () => {
    const activeSessionId = currentSessionId;
    if (activeSessionId) {
      try {
        await api.stopChat(activeSessionId);
      } catch (e) {
        console.warn('Failed to call stopChat endpoint', e);
      }
    }
    setLoading(false);
    toast({
      title: 'Inference Stopped',
      description: 'Chat request stopped by operator.',
      type: 'warn',
    });
  };

  // Living Requirements & Architecture handlers
  const handleUpdateRequirements = async (updatedMd: string) => {
    const activeSessionId = currentSessionId;
    if (!activeSessionId) return;
    try {
      const res = await api.updateSessionRequirements(activeSessionId, updatedMd);
      setCurrentRequirementsMd(res.requirements_md);
      toast({
        title: 'Requirements Updated',
        description: 'Living architecture specification updated.',
        type: 'success',
      });
    } catch (err: any) {
      toast({
        title: 'Save Failed',
        description: err.message || 'Could not update requirements',
        type: 'crit',
      });
    }
  };

  const handlePlanFromRequirements = async () => {
    const activeSessionId = currentSessionId;
    if (!activeSessionId) return;
    setLoading(true);
    try {
      const res = await api.planFromRequirements(activeSessionId, targetProvider, targetEnvironment);
      if (res.requirements_md) {
        setCurrentRequirementsMd(res.requirements_md);
      }
      if (res.status === 'plan_ready' && res.plan) {
        setCurrentPlan(res.plan);
        setDriftDiff(null);
        const assistantMsg: ChatMessage = {
          id: Math.random().toString(36).substring(2, 9),
          sender: 'assistant',
          text: `Plan synthesized from requirements: ${res.plan.plan_id} (${res.plan.intent.replace(/_/g, ' ')}). Review the topology, schema, and security checks in the workspace pane.`,
          timestamp: new Date().toISOString(),
          rag_citations: res.rag_citations,
          requirements_md: res.requirements_md,
        };
        setMessages((prev) => [...prev, assistantMsg]);
        refreshRecentPlans();
        toast({
          title: 'Plan Synthesized',
          description: `Plan ${res.plan.plan_id} generated from requirements specification.`,
          type: 'success',
        });
      } else {
        toast({
          title: 'Synthesis Note',
          description: res.message || 'No plan generated.',
          type: 'info',
        });
      }
    } catch (err: any) {
      toast({
        title: 'Plan Generation Failed',
        description: err.message || 'Failed to synthesize plan from requirements',
        type: 'crit',
      });
    } finally {
      setLoading(false);
    }
  };

  // Re-execute plan handler (M-13 Safety First)
  const handleReexecutePlan = async () => {
    if (!currentPlan) return;
    setLoading(true);
    try {
      const idempotencyKey = `idem-${currentPlan.plan_id}-${Date.now()}`;
      const res = await api.reexecutePlan(currentPlan.plan_id, idempotencyKey);
      if (res.status === 'noop') {
        toast({
          title: 'Infrastructure Already Matches Plan',
          description: 'Dry-run verified zero drift. REEXEC_NOOP recorded in immutable audit log.',
          type: 'info',
        });
        setDriftDiff(null);
      } else if (res.status === 'drift_detected') {
        setDriftDiff(res.diff);
        setCurrentPlan((prev) =>
          prev
            ? {
                ...prev,
                status: 'awaiting_approval',
                risk_level: 'high',
                requires_confirmation_text: res.requires_confirmation_text,
                confirmation_phrase: res.confirmation_phrase,
              }
            : null
        );
        toast({
          title: 'Drift Detected (Dry-Run Only)',
          description: 'Infrastructure has drifted. Fresh human approval is required before restoring.',
          type: 'crit',
        });
      }
    } catch (err: any) {
      toast({
        title: 'Re-execution Error',
        description: err.message || 'Failed to dry-run re-execute plan',
        type: 'crit',
      });
    } finally {
      setLoading(false);
    }
  };

  // Human approval handler
  const handleApprovePlan = async (confirmationText?: string, customTf?: string, customSql?: string) => {
    if (!currentPlan) return;
    setLoading(true);
    try {
      await api.submitApproval(currentPlan.plan_id, 'approve', {
        confirmationText,
        customTerraform: customTf,
        customSql,
      });
      toast({
        title: 'Plan Approved',
        description: `Plan ${currentPlan.plan_id} approved. Starting execution.`,
        type: 'success',
      });
      setExecutingPlanId(currentPlan.plan_id);
      changeView('executions');
    } catch (err: any) {
      toast({
        title: 'Approval Rejected',
        description: err.message || 'Approval submission failed',
        type: 'crit',
      });
    } finally {
      setLoading(false);
    }
  };

  // Reject plan handler
  const handleRejectPlan = async () => {
    if (!currentPlan) return;
    try {
      await api.submitApproval(currentPlan.plan_id, 'reject');
      toast({
        title: 'Plan Rejected',
        description: `Plan ${currentPlan.plan_id} has been marked as rejected.`,
        type: 'warn',
      });
      setCurrentPlan(null);
    } catch (err: any) {
      toast({
        title: 'Error',
        description: err.message || 'Failed to reject plan',
        type: 'crit',
      });
    }
  };

  // Modify plan handler
  const handleModifyPlan = async (modifications: string) => {
    if (!currentPlan) return;
    setLoading(true);
    try {
      const response = await api.submitApproval(currentPlan.plan_id, 'modify', { modifications });
      if (response.plan) {
        setCurrentPlan(response.plan);
        const modMsg: ChatMessage = {
          id: Math.random().toString(36).substring(2, 9),
          sender: 'assistant',
          text: `Revised plan updated with changes: "${modifications}"`,
          timestamp: new Date().toISOString(),
        };
        setMessages((prev) => [...prev, modMsg]);
        toast({
          title: 'Plan Updated',
          description: 'Modifications incorporated into the architecture.',
          type: 'success',
        });
      }
    } catch (err: any) {
      toast({
        title: 'Modification Failed',
        description: err.message || 'Failed to apply modifications',
        type: 'crit',
      });
    } finally {
      setLoading(false);
    }
  };

  // Load a plan from plans view
  const handleSelectPlan = async (planId: string) => {
    setLoading(true);
    try {
      const plan = await api.getPlan(planId);
      setCurrentPlan(plan);
      changeView('designer');
      toast({
        title: 'Plan Loaded',
        description: `Loaded plan ${planId} in Designer.`,
        type: 'info',
      });
    } catch (err) {
      toast({
        title: 'Failed to Load Plan',
        description: `Could not retrieve plan ${planId}`,
        type: 'crit',
      });
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="h-screen w-screen flex flex-col bg-base text-ink-primary overflow-hidden font-sans select-none">
      {/* Topbar */}
      <Topbar
        onToggleSidebar={handleToggleSidebar}
        onOpenCommandPalette={() => setCommandPaletteOpen(true)}
        sidebarCollapsed={sidebarCollapsed}
        wsConnected={Boolean(executingPlanId)}
        onSelectView={changeView}
        currentProvider={targetProvider}
        currentEnvironment={targetEnvironment}
        onTargetChange={handleTargetChange}
      />

      {/* Main Layout Area: Sidebar + Content */}
      <div className="flex-1 flex overflow-hidden">
        {/* Collapsible Sidebar */}
        <Sidebar
          activeView={activeView}
          onSelectView={(v) => {
            changeView(v);
          }}
          collapsed={sidebarCollapsed}
          onToggleCollapse={handleToggleSidebar}
          plansCount={recentPlanIds.length}
          isExecutionRunning={Boolean(executingPlanId)}
          isTargetHealthy={true}
          environment={targetEnvironment}
        />

        {/* Content View Container */}
        <main
          className="flex-1 overflow-y-auto bg-base p-6 select-text"
          id="main-content"
          tabIndex={-1}
        >
          <div className="max-w-[1440px] w-full mx-auto">
            {activeView === 'designer' && (
              <DesignerScreen
                messages={messages}
                onSendMessage={handleSendMessage}
                isLoading={loading}
                currentPlan={currentPlan}
                onApprovePlan={handleApprovePlan}
                onRejectPlan={handleRejectPlan}
                onModifyPlan={handleModifyPlan}
                onClearHistory={handleClearHistory}
                onOpenHistory={() => setSessionDrawerOpen(true)}
                onNewChat={handleNewChat}
                sessionTitle={currentSessionTitle}
                onReexecutePlan={handleReexecutePlan}
                onViewExecution={() => {
                  if (currentPlan) {
                    setExecutingPlanId(currentPlan.plan_id);
                    changeView('executions');
                  }
                }}
                onViewAudit={() => changeView('audit')}
                driftDiff={driftDiff}
                requirementsMd={currentRequirementsMd}
                onUpdateRequirements={handleUpdateRequirements}
                onSynthesizePlan={handlePlanFromRequirements}
                onCancelChat={handleCancelChat}
              />
            )}

            {activeView === 'plans' && (
              <PlansView
                onSelectPlan={handleSelectPlan}
                onGoToDesigner={() => changeView('designer')}
              />
            )}

            {activeView === 'executions' && (
              <ExecutionsView
                activeExecutingPlanId={executingPlanId}
                onClearExecutingPlan={() => setExecutingPlanId(null)}
                onGoToDesigner={(pid) => {
                  if (pid) handleSelectPlan(pid);
                  else changeView('designer');
                }}
                onViewAudit={() => changeView('audit')}
                onStartExecution={(planId) => {
                  setExecutingPlanId(planId);
                }}
              />
            )}

            {activeView === 'audit' && (
              <AuditLogViewer
                onGoToDesigner={() => changeView('designer')}
              />
            )}

            {activeView === 'connections' && <ConnectionsView />}

            {activeView === 'settings' && <SettingsView />}
          </div>
        </main>
      </div>

      {/* Persistent Statusbar */}
      <Statusbar
        activePlanId={currentPlan?.plan_id}
        environment={targetEnvironment}
        lastVerificationTime={lastVerifyTime}
        onPlanClick={(pid) => {
          handleSelectPlan(pid);
        }}
      />

      {/* ⌘K Command Palette Modal */}
      <CommandPalette
        isOpen={commandPaletteOpen}
        onClose={() => setCommandPaletteOpen(false)}
        onNavigate={(v) => changeView(v as NavView)}
        onSelectPrompt={(p) => handleSendMessage(p)}
        recentPlanIds={recentPlanIds}
        onSelectPlan={handleSelectPlan}
        onToggleSidebar={handleToggleSidebar}
      />

      {/* M-13 Session History Drawer */}
      <SessionDrawer
        isOpen={sessionDrawerOpen}
        onClose={() => setSessionDrawerOpen(false)}
        sessions={sessions}
        currentSessionId={currentSessionId}
        onSelectSession={handleSelectSession}
        onNewChat={handleNewChat}
        onRenameSession={handleRenameSession}
        onDeleteSession={handleDeleteSession}
        onSearchChange={loadSessions}
      />
    </div>
  );
};

export default App;
