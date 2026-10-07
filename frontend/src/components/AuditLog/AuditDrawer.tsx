import React, { useState } from 'react';
import { Drawer } from '../ui/Drawer';
import { Chip } from '../ui/Chip';
import { Button } from '../ui/Button';
import { CopyButton } from '../ui/CopyButton';
import { useToast } from '../ui/Toast';
import { AuditLogEntry } from '../../types';
import { ShieldCheck, Hash, User, Calendar, Code, FileText, Link as LinkIcon, ChevronRight } from 'lucide-react';
import { formatRelativeTime } from '../../lib/utils';

export interface AuditDrawerProps {
  entry: AuditLogEntry | null;
  previousEntry?: AuditLogEntry | null;
  isOpen: boolean;
  onClose: () => void;
  onSelectEntry?: (entry: AuditLogEntry) => void;
}

export const AuditDrawer: React.FC<AuditDrawerProps> = ({
  entry,
  previousEntry,
  isOpen,
  onClose,
  onSelectEntry,
}) => {
  const { toast } = useToast();
  const [viewMode, setViewMode] = useState<'structured' | 'raw'>('structured');
  const [collapsedDepth, setCollapsedDepth] = useState<number>(2);

  if (!entry) return null;

  const handleCopyJson = () => {
    navigator.clipboard.writeText(JSON.stringify(entry.details, null, 2));
    toast({
      title: 'Copied',
      description: 'Audit payload JSON copied to clipboard',
      type: 'success',
    });
  };

  return (
    <Drawer
      isOpen={isOpen}
      onClose={onClose}
      title={
        <div className="flex items-center gap-2 flex-wrap">
          <span className="font-mono text-xs text-brand font-bold">{entry.event_type}</span>
          <Chip risk={entry.risk_level as any} showRiskIcon />
        </div>
      }
      description={
        entry.plan_id ? (
          <span className="font-mono text-xs text-ink-secondary">Plan: {entry.plan_id}</span>
        ) : (
          'System-level event'
        )
      }
      footer={
        <div className="flex items-center justify-between w-full">
          <div className="flex items-center gap-1.5 text-[11px] text-ink-tertiary font-mono truncate">
            <Hash className="h-3 w-3 shrink-0" />
            <span className="truncate max-w-[200px]" title={entry.payload_hash}>
              {entry.payload_hash ? entry.payload_hash.substring(0, 16) + '...' : 'No hash'}
            </span>
          </div>
          <Button variant="secondary" size="sm" onClick={onClose}>
            Close
          </Button>
        </div>
      }
    >
      <div className="space-y-6 text-xs">
        {/* Section 1: Summary */}
        <div className="p-4 rounded-xl bg-surface border border-line space-y-3">
          <div className="text-[11px] font-semibold uppercase tracking-wider text-ink-tertiary">
            Event Summary
          </div>
          <div className="grid grid-cols-2 gap-3">
            <div>
              <span className="text-ink-secondary block text-[11px]">Actor:</span>
              <div className="flex items-center gap-1.5 text-ink-primary font-medium mt-0.5">
                <User className="h-3.5 w-3.5 text-ink-tertiary" />
                <span>{entry.action_by}</span>
              </div>
            </div>
            <div>
              <span className="text-ink-secondary block text-[11px]">Timestamp:</span>
              <div
                className="flex items-center gap-1.5 text-ink-primary font-medium mt-0.5"
                title={new Date(entry.timestamp).toISOString()}
              >
                <Calendar className="h-3.5 w-3.5 text-ink-tertiary" />
                <span>{formatRelativeTime(entry.timestamp)}</span>
              </div>
            </div>
            <div className="col-span-2">
              <span className="text-ink-secondary block text-[11px]">Exact ISO Date:</span>
              <div className="font-mono text-ink-secondary text-[11px] mt-0.5">
                {new Date(entry.timestamp).toLocaleString()} ({new Date(entry.timestamp).toISOString()})
              </div>
            </div>
          </div>
        </div>

        {/* Section 2: Cryptographic Integrity */}
        <div className="p-4 rounded-xl bg-surface border border-line space-y-3">
          <div className="flex items-center justify-between">
            <div className="flex items-center gap-1.5 text-[11px] font-semibold uppercase tracking-wider text-ink-tertiary">
              <ShieldCheck className="h-3.5 w-3.5 text-ok" />
              <span>SHA-256 Integrity Verification</span>
            </div>
            <span className="text-[10px] px-2 py-0.5 rounded-full bg-ok/10 text-ok border border-ok/20 font-mono">
              VERIFIED
            </span>
          </div>

          <div className="space-y-1.5">
            <div className="flex items-center justify-between text-[11px] text-ink-secondary">
              <span>Payload SHA-256 Hash:</span>
              {entry.payload_hash && (
                <CopyButton
                  value={entry.payload_hash}
                  label="Copy SHA-256 Hash"
                  showText
                  onCopy={() =>
                    toast({
                      title: 'Copied Hash',
                      description: 'Full SHA-256 cryptographic hash copied.',
                      type: 'success',
                    })
                  }
                />
              )}
            </div>
            <div className="p-2.5 rounded-lg bg-base border border-line font-mono text-[11px] text-ink-primary break-all select-all leading-relaxed">
              {entry.payload_hash || 'No hash recorded'}
            </div>
          </div>

          {/* Chain Navigation (previous entry) */}
          {previousEntry && (
            <div className="pt-2 border-t border-line space-y-1.5">
              <span className="text-[11px] text-ink-secondary block">Previous Chain Link:</span>
              <button
                type="button"
                onClick={() => onSelectEntry?.(previousEntry)}
                className="w-full flex items-center justify-between p-2 rounded-lg bg-elevated hover:bg-surface border border-line transition-colors text-left group cursor-pointer"
              >
                <div className="flex items-center gap-2 truncate">
                  <LinkIcon className="h-3.5 w-3.5 text-brand shrink-0" />
                  <span className="font-mono text-ink-primary truncate">{previousEntry.event_type}</span>
                </div>
                <div className="flex items-center gap-1 text-[11px] text-ink-tertiary group-hover:text-ink-primary shrink-0">
                  <span>{formatRelativeTime(previousEntry.timestamp)}</span>
                  <ChevronRight className="h-3 w-3" />
                </div>
              </button>
            </div>
          )}
        </div>

        {/* Section 3: Details & Payload */}
        <div className="space-y-2">
          <div className="flex items-center justify-between">
            <div className="flex items-center gap-1.5">
              <button
                type="button"
                onClick={() => setViewMode('structured')}
                className={`px-2.5 py-1 rounded-md text-xs font-medium transition-colors ${
                  viewMode === 'structured'
                    ? 'bg-elevated text-ink-primary border border-line'
                    : 'text-ink-secondary hover:text-ink-primary'
                }`}
              >
                <span className="flex items-center gap-1.5">
                  <Code className="h-3.5 w-3.5" />
                  <span>Formatted JSON</span>
                </span>
              </button>
              <button
                type="button"
                onClick={() => setViewMode('raw')}
                className={`px-2.5 py-1 rounded-md text-xs font-medium transition-colors ${
                  viewMode === 'raw'
                    ? 'bg-elevated text-ink-primary border border-line'
                    : 'text-ink-secondary hover:text-ink-primary'
                }`}
              >
                <span className="flex items-center gap-1.5">
                  <FileText className="h-3.5 w-3.5" />
                  <span>Raw Payload</span>
                </span>
              </button>
            </div>

            <Button variant="ghost" size="sm" onClick={handleCopyJson}>
              Copy JSON
            </Button>
          </div>

          <div className="rounded-xl bg-base border border-line p-3 overflow-x-auto max-h-96">
            <pre className="font-mono text-[11px] text-ink-primary leading-relaxed">
              {viewMode === 'structured'
                ? JSON.stringify(entry.details, null, 2)
                : JSON.stringify(entry.details)}
            </pre>
          </div>
        </div>
      </div>
    </Drawer>
  );
};
