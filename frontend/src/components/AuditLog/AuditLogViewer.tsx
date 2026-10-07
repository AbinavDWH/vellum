import React, { useEffect, useState, useMemo, useRef } from 'react';
import {
  History,
  ShieldCheck,
  Search,
  RefreshCw,
  Download,
  ChevronDown,
  ChevronRight,
  User,
  Clock,
  Hash,
  CheckCircle2,
  AlertTriangle,
  ShieldAlert,
  Play,
  FileCode,
  FileSpreadsheet,
} from 'lucide-react';
import { useVirtualizer } from '@tanstack/react-virtual';
import { AuditLogEntry } from '../../types';
import { api } from '../../services/api';
import { Button } from '../ui/Button';
import { Chip } from '../ui/Chip';
import { CopyButton } from '../ui/CopyButton';
import { EmptyState } from '../ui/EmptyState';
import { Skeleton } from '../ui/Skeleton';
import { useToast } from '../ui/Toast';
import { AuditDrawer } from './AuditDrawer';
import { formatRelativeTime } from '../../lib/utils';

export interface AuditLogViewerProps {
  onGoToDesigner?: () => void;
}

interface PlanGroup {
  planId: string;
  highestRisk: 'low' | 'medium' | 'high' | 'critical';
  events: AuditLogEntry[];
  startTime: string;
  endTime: string;
}

export const AuditLogViewer: React.FC<AuditLogViewerProps> = ({ onGoToDesigner }) => {
  const { toast } = useToast();
  const [logs, setLogs] = useState<AuditLogEntry[]>([]);
  const [loading, setLoading] = useState(true);
  const [searchQuery, setSearchQuery] = useState('');
  const [selectedRisk, setSelectedRisk] = useState<string>('all');
  const [selectedEventType, setSelectedEventType] = useState<string>('all');
  const [collapsedGroups, setCollapsedGroups] = useState<Record<string, boolean>>({});

  // Active drawer state
  const [selectedEntry, setSelectedEntry] = useState<AuditLogEntry | null>(null);
  const [isDrawerOpen, setIsDrawerOpen] = useState(false);

  const fetchLogs = async () => {
    setLoading(true);
    try {
      const data = await api.getAuditLogs();
      setLogs(data);
    } catch (err) {
      console.error('Failed to fetch audit trail', err);
      toast({
        title: 'Error',
        description: 'Failed to load immutable audit records.',
        type: 'crit',
      });
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    fetchLogs();
  }, []);

  // Distinct event types
  const eventTypes = useMemo(() => {
    const set = new Set<string>();
    logs.forEach((l) => set.add(l.event_type));
    return Array.from(set).sort();
  }, [logs]);

  // Filtered logs
  const filteredLogs = useMemo(() => {
    return logs.filter((log) => {
      // Risk filter
      if (selectedRisk !== 'all' && log.risk_level.toLowerCase() !== selectedRisk.toLowerCase()) {
        return false;
      }
      // Event type filter
      if (selectedEventType !== 'all' && log.event_type !== selectedEventType) {
        return false;
      }
      // Search query
      if (searchQuery.trim()) {
        const q = searchQuery.toLowerCase();
        const matchesPlan = log.plan_id ? log.plan_id.toLowerCase().includes(q) : false;
        const matchesEvent = log.event_type.toLowerCase().includes(q);
        const matchesActor = log.action_by.toLowerCase().includes(q);
        const matchesHash = log.payload_hash ? log.payload_hash.toLowerCase().includes(q) : false;
        const matchesDetails = JSON.stringify(log.details).toLowerCase().includes(q);
        return matchesPlan || matchesEvent || matchesActor || matchesHash || matchesDetails;
      }
      return true;
    });
  }, [logs, selectedRisk, selectedEventType, searchQuery]);

  // Group by plan_id
  const planGroups = useMemo<PlanGroup[]>(() => {
    const groupsMap = new Map<string, AuditLogEntry[]>();

    filteredLogs.forEach((log) => {
      const key = log.plan_id || 'system_events';
      if (!groupsMap.has(key)) {
        groupsMap.set(key, []);
      }
      groupsMap.get(key)!.push(log);
    });

    const result: PlanGroup[] = [];
    const riskPriority: Record<string, number> = {
      critical: 4,
      high: 3,
      medium: 2,
      low: 1,
    };

    groupsMap.forEach((events, planId) => {
      let highestRisk: 'low' | 'medium' | 'high' | 'critical' = 'low';
      let highestVal = 0;

      events.forEach((ev) => {
        const val = riskPriority[ev.risk_level?.toLowerCase()] || 1;
        if (val > highestVal) {
          highestVal = val;
          highestRisk = (ev.risk_level?.toLowerCase() as any) || 'low';
        }
      });

      const sorted = [...events].sort(
        (a, b) => new Date(b.timestamp).getTime() - new Date(a.timestamp).getTime()
      );

      result.push({
        planId,
        highestRisk,
        events: sorted,
        startTime: sorted[sorted.length - 1].timestamp,
        endTime: sorted[0].timestamp,
      });
    });

    return result;
  }, [filteredLogs]);

  const toggleGroupCollapse = (planId: string) => {
    setCollapsedGroups((prev) => ({
      ...prev,
      [planId]: !prev[planId],
    }));
  };

  const handleOpenDrawer = (entry: AuditLogEntry) => {
    setSelectedEntry(entry);
    setIsDrawerOpen(true);
  };

  const handleExportJson = () => {
    const dataStr = 'data:text/json;charset=utf-8,' + encodeURIComponent(JSON.stringify(filteredLogs, null, 2));
    const a = document.createElement('a');
    a.setAttribute('href', dataStr);
    a.setAttribute('download', `vellum-audit-${new Date().toISOString().substring(0, 10)}.json`);
    document.body.appendChild(a);
    a.click();
    a.remove();
    toast({
      title: 'Export Complete',
      description: 'Audit log exported as JSON.',
      type: 'success',
    });
  };

  const handleExportCsv = () => {
    const headers = ['timestamp', 'event_type', 'plan_id', 'risk_level', 'action_by', 'payload_hash'];
    const rows = filteredLogs.map((l) => [
      l.timestamp,
      l.event_type,
      l.plan_id || '',
      l.risk_level,
      l.action_by,
      l.payload_hash || '',
    ]);

    const csvContent =
      'data:text/csv;charset=utf-8,' +
      [headers.join(','), ...rows.map((e) => e.map((val) => `"${val}"`).join(','))].join('\n');

    const a = document.createElement('a');
    a.setAttribute('href', encodeURI(csvContent));
    a.setAttribute('download', `vellum-audit-${new Date().toISOString().substring(0, 10)}.csv`);
    document.body.appendChild(a);
    a.click();
    a.remove();
    toast({
      title: 'Export Complete',
      description: 'Audit log exported as CSV.',
      type: 'success',
    });
  };

  const getEventIcon = (eventType: string) => {
    const t = eventType.toUpperCase();
    if (t.includes('APPROVAL_GRANTED') || t.includes('VERIFICATION_PASSED')) {
      return <CheckCircle2 className="h-3.5 w-3.5 text-ok shrink-0" />;
    }
    if (t.includes('REJECTED') || t.includes('FAILED') || t.includes('ERROR')) {
      return <ShieldAlert className="h-3.5 w-3.5 text-crit shrink-0" />;
    }
    if (t.includes('DRIFT')) {
      return <AlertTriangle className="h-3.5 w-3.5 text-warn shrink-0" />;
    }
    if (t.includes('EXECUTION')) {
      return <Play className="h-3.5 w-3.5 text-info shrink-0" />;
    }
    return <FileCode className="h-3.5 w-3.5 text-brand shrink-0" />;
  };

  // Find previous entry in chain for selected entry
  const previousEntry = useMemo(() => {
    if (!selectedEntry) return null;
    const idx = logs.findIndex(
      (l) => l.payload_hash === selectedEntry.payload_hash && l.timestamp === selectedEntry.timestamp
    );
    if (idx > 0) {
      return logs[idx - 1];
    }
    return null;
  }, [logs, selectedEntry]);

  // Virtualizer for smooth rendering
  const parentRef = useRef<HTMLDivElement>(null);
  const rowVirtualizer = useVirtualizer({
    count: planGroups.length,
    getScrollElement: () => parentRef.current,
    estimateSize: () => 140,
    overscan: 5,
  });

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex flex-wrap items-center justify-between gap-4">
        <div>
          <div className="flex items-center gap-2">
            <h1 className="text-xl font-bold tracking-tight text-ink-primary">Immutable Audit Trail</h1>
            <span className="text-xs font-mono px-2 py-0.5 rounded-full bg-brand/10 text-brand border border-brand/20">
              {logs.length} records
            </span>
          </div>
          <p className="text-xs text-ink-secondary">
            Cryptographically sealed event ledger verifying all plan approvals, executions, and drift checks
          </p>
        </div>

        <div className="flex items-center gap-2 flex-wrap">
          <Button
            variant="secondary"
            size="sm"
            onClick={fetchLogs}
            disabled={loading}
            leftIcon={<RefreshCw className={`h-3.5 w-3.5 ${loading ? 'animate-spin' : ''}`} />}
          >
            Refresh
          </Button>

          <Button
            variant="outline"
            size="sm"
            onClick={handleExportJson}
            disabled={filteredLogs.length === 0}
            leftIcon={<Download className="h-3.5 w-3.5" />}
          >
            Export JSON
          </Button>

          <Button
            variant="outline"
            size="sm"
            onClick={handleExportCsv}
            disabled={filteredLogs.length === 0}
            leftIcon={<FileSpreadsheet className="h-3.5 w-3.5" />}
          >
            Export CSV
          </Button>
        </div>
      </div>

      {/* Filter Toolbar */}
      <div className="flex flex-wrap items-center justify-between gap-3 p-3 rounded-xl bg-surface border border-line">
        {/* Search */}
        <div className="flex items-center gap-2 flex-1 min-w-[240px] max-w-md">
          <Search className="h-4 w-4 text-ink-tertiary" aria-hidden="true" />
          <input
            type="text"
            value={searchQuery}
            onChange={(e) => setSearchQuery(e.target.value)}
            placeholder="Search plan ID, event, actor, or payload..."
            className="w-full bg-transparent text-xs text-ink-primary placeholder-ink-tertiary focus:outline-none"
          />
        </div>

        {/* Filters */}
        <div className="flex items-center gap-4 flex-wrap">
          {/* Event type dropdown */}
          <div className="flex items-center gap-2">
            <span className="text-xs text-ink-tertiary">Event:</span>
            <select
              value={selectedEventType}
              onChange={(e) => setSelectedEventType(e.target.value)}
              className="bg-elevated border border-line rounded-lg px-2.5 py-1 text-xs text-ink-primary focus:outline-none focus:ring-1 focus:ring-brand"
            >
              <option value="all">All Events</option>
              {eventTypes.map((et) => (
                <option key={et} value={et}>
                  {et}
                </option>
              ))}
            </select>
          </div>

          {/* Risk Filter Chips */}
          <div className="flex items-center gap-1.5">
            <span className="text-xs text-ink-tertiary mr-1">Risk:</span>
            {['all', 'low', 'medium', 'high', 'critical'].map((r) => (
              <button
                key={r}
                type="button"
                onClick={() => setSelectedRisk(r)}
                className={`px-2 py-0.5 rounded-full text-xs font-medium uppercase transition-colors cursor-pointer ${
                  selectedRisk === r
                    ? 'bg-brand/20 text-brand border border-brand/40'
                    : 'bg-elevated text-ink-secondary hover:text-ink-primary border border-line'
                }`}
              >
                {r}
              </button>
            ))}
          </div>
        </div>
      </div>

      {/* Main Content */}
      {loading ? (
        <div className="space-y-4">
          {[...Array(4)].map((_, i) => (
            <Skeleton key={i} className="h-28 w-full" />
          ))}
        </div>
      ) : planGroups.length === 0 ? (
        <EmptyState
          icon={<History className="h-6 w-6 text-brand" />}
          title="No audit records yet — run your first plan."
          hint="Every infrastructure plan generation, approval, execution, and verification creates an immutable cryptographic log entry."
          actionLabel="Go to Designer"
          onAction={onGoToDesigner}
        />
      ) : (
        <div
          ref={parentRef}
          className="space-y-4 max-h-[750px] overflow-y-auto pr-1"
        >
          {planGroups.map((group) => {
            const isCollapsed = collapsedGroups[group.planId];

            return (
              <div
                key={group.planId}
                className="rounded-xl bg-surface border border-line overflow-hidden transition-colors"
              >
                {/* Collapsible Group Header */}
                <div
                  onClick={() => toggleGroupCollapse(group.planId)}
                  className="px-4 py-3 bg-elevated/70 hover:bg-elevated border-b border-line flex flex-wrap items-center justify-between gap-3 cursor-pointer select-none transition-colors"
                >
                  <div className="flex items-center gap-3">
                    <button
                      type="button"
                      aria-label={isCollapsed ? 'Expand group' : 'Collapse group'}
                      className="p-1 rounded text-ink-secondary hover:text-ink-primary"
                    >
                      {isCollapsed ? (
                        <ChevronRight className="h-4 w-4" />
                      ) : (
                        <ChevronDown className="h-4 w-4" />
                      )}
                    </button>

                    <div className="flex items-center gap-2">
                      <span className="font-mono text-xs font-bold text-ink-primary">
                        {group.planId === 'system_events' ? 'General System Events' : group.planId}
                      </span>
                      {group.planId !== 'system_events' && (
                        <CopyButton
                          value={group.planId}
                          label="Copy plan ID"
                          className="h-4 w-4 p-0"
                          onCopy={() =>
                            toast({
                              title: 'Copied',
                              description: `Plan ID ${group.planId} copied.`,
                              type: 'success',
                            })
                          }
                        />
                      )}
                    </div>

                    <Chip risk={group.highestRisk} showRiskIcon />

                    <span className="text-[11px] font-mono px-2 py-0.5 rounded bg-surface border border-line text-ink-secondary">
                      {group.events.length} {group.events.length === 1 ? 'event' : 'events'}
                    </span>
                  </div>

                  <div className="text-[11px] text-ink-tertiary flex items-center gap-2 font-mono">
                    <Clock className="h-3.5 w-3.5" />
                    <span>
                      {formatRelativeTime(group.endTime)}
                    </span>
                  </div>
                </div>

                {/* Rows inside group */}
                {!isCollapsed && (
                  <div className="overflow-x-auto">
                    <table className="w-full text-left text-xs">
                      <thead className="text-[11px] font-semibold uppercase tracking-wider text-ink-secondary bg-surface/50 border-b border-line">
                        <tr>
                          <th className="px-4 py-2.5">Event</th>
                          <th className="px-4 py-2.5">Risk</th>
                          <th className="px-4 py-2.5">Actor</th>
                          <th className="px-4 py-2.5">Time</th>
                          <th className="px-4 py-2.5">SHA-256 Hash</th>
                        </tr>
                      </thead>
                      <tbody className="divide-y divide-line/60">
                        {group.events.map((event, idx) => (
                          <tr
                            key={idx}
                            onClick={() => handleOpenDrawer(event)}
                            className="hover:bg-elevated transition-colors cursor-pointer group"
                          >
                            {/* Event */}
                            <td className="px-4 py-3 text-ink-primary font-medium">
                              <div className="flex items-center gap-2">
                                {getEventIcon(event.event_type)}
                                <span className="font-mono text-xs group-hover:text-brand transition-colors">
                                  {event.event_type}
                                </span>
                              </div>
                            </td>

                            {/* Risk Chip */}
                            <td className="px-4 py-3">
                              <Chip risk={event.risk_level as any} />
                            </td>

                            {/* Actor */}
                            <td className="px-4 py-3 text-ink-secondary">
                              <div className="flex items-center gap-1.5">
                                <User className="h-3 w-3 text-ink-tertiary" />
                                <span>{event.action_by}</span>
                              </div>
                            </td>

                            {/* Time */}
                            <td
                              className="px-4 py-3 text-ink-secondary whitespace-nowrap text-[11px]"
                              title={new Date(event.timestamp).toISOString()}
                            >
                              {formatRelativeTime(event.timestamp)}
                            </td>

                            {/* Hash (12 chars + copy) */}
                            <td className="px-4 py-3 text-ink-tertiary font-mono">
                              <div className="flex items-center gap-1.5">
                                <span>
                                  {event.payload_hash ? `${event.payload_hash.substring(0, 12)}...` : '-'}
                                </span>
                                {event.payload_hash && (
                                  <CopyButton
                                    value={event.payload_hash}
                                    label="Copy full hash"
                                    className="h-4 w-4 p-0 opacity-70 group-hover:opacity-100"
                                    onCopy={() =>
                                      toast({
                                        title: 'Copied Hash',
                                        description: 'SHA-256 hash copied to clipboard.',
                                        type: 'success',
                                      })
                                    }
                                  />
                                )}
                              </div>
                            </td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                )}
              </div>
            );
          })}
        </div>
      )}

      {/* Details Right Drawer */}
      <AuditDrawer
        isOpen={isDrawerOpen}
        onClose={() => setIsDrawerOpen(false)}
        entry={selectedEntry}
        previousEntry={previousEntry}
        onSelectEntry={(newEntry) => setSelectedEntry(newEntry)}
      />
    </div>
  );
};
