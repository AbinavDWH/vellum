import React from 'react';
import { CopyButton } from '../ui/CopyButton';
import { Tooltip } from '../ui/Tooltip';
import { ShieldCheck, Cloud, Clock } from 'lucide-react';

export interface StatusbarProps {
  activePlanId?: string | null;
  environment?: string;
  lastVerificationTime?: string | null;
  onPlanClick?: (planId: string) => void;
}

export const Statusbar: React.FC<StatusbarProps> = ({
  activePlanId,
  environment = 'local',
  lastVerificationTime,
  onPlanClick,
}) => {
  return (
    <footer className="h-7 bg-surface border-t border-line px-4 flex items-center justify-between text-[11px] text-ink-secondary select-none shrink-0 z-30">
      {/* Left: Active plan indicator */}
      <div className="flex items-center gap-3 truncate">
        {activePlanId ? (
          <div className="flex items-center gap-1.5 font-mono">
            <span className="text-ink-tertiary">Active Plan:</span>
            <button
              onClick={() => onPlanClick?.(activePlanId)}
              className="text-brand-text hover:underline font-semibold cursor-pointer focus-visible:outline-none"
            >
              {activePlanId}
            </button>
            <CopyButton value={activePlanId} label="Copy plan ID" className="h-4 w-4 p-0" />
          </div>
        ) : (
          <span className="text-ink-tertiary">No active plan selected</span>
        )}

        <span className="text-line">|</span>

        {/* Cloud env */}
        <div className="flex items-center gap-1.5">
          <Cloud className="h-3 w-3 text-ink-tertiary" aria-hidden="true" />
          <span>env={environment}</span>
        </div>
      </div>

      {/* Right: Verification status & clock */}
      <div className="flex items-center gap-3 shrink-0">
        {lastVerificationTime ? (
          <div className="flex items-center gap-1.5">
            <ShieldCheck className="h-3 w-3 text-ok" aria-hidden="true" />
            <span>last verify {lastVerificationTime}</span>
          </div>
        ) : (
          <div className="flex items-center gap-1.5 text-ink-tertiary">
            <Clock className="h-3 w-3" aria-hidden="true" />
            <span>verification standby</span>
          </div>
        )}
        <span className="text-line">|</span>
        <span className="text-ink-tertiary">Vellum Engine Active</span>
      </div>
    </footer>
  );
};
