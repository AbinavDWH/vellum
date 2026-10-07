import React from 'react';
import { cn } from '../../lib/utils';
import { ShieldCheck, AlertTriangle, ShieldAlert, AlertOctagon } from 'lucide-react';

export type RiskLevel = 'low' | 'medium' | 'high' | 'critical' | 'LOW' | 'MEDIUM' | 'HIGH' | 'CRITICAL';
export type StatusVariant = 'ok' | 'warn' | 'high' | 'crit' | 'info' | 'brand' | 'neutral';

export interface ChipProps extends React.HTMLAttributes<HTMLSpanElement> {
  risk?: RiskLevel;
  variant?: StatusVariant;
  icon?: React.ReactNode;
  showRiskIcon?: boolean;
}

export const Chip: React.FC<ChipProps> = ({
  risk,
  variant,
  icon,
  showRiskIcon = false,
  className,
  children,
  ...props
}) => {
  let activeVariant: StatusVariant = variant || 'neutral';
  let defaultIcon: React.ReactNode = null;

  if (risk) {
    const normalized = risk.toLowerCase();
    if (normalized === 'low') {
      activeVariant = 'ok';
      defaultIcon = <ShieldCheck className="h-3 w-3 shrink-0" aria-hidden="true" />;
    } else if (normalized === 'medium') {
      activeVariant = 'warn';
      defaultIcon = <AlertTriangle className="h-3 w-3 shrink-0" aria-hidden="true" />;
    } else if (normalized === 'high') {
      activeVariant = 'high';
      defaultIcon = <ShieldAlert className="h-3 w-3 shrink-0" aria-hidden="true" />;
    } else if (normalized === 'critical') {
      activeVariant = 'crit';
      defaultIcon = <AlertOctagon className="h-3 w-3 shrink-0" aria-hidden="true" />;
    }
  }

  // Chips = tint background + full-color text + 1px 30% tint border. Never solid fills.
  const variants: Record<StatusVariant, string> = {
    ok: 'bg-risk-low-dim text-ok border-ok/30',
    warn: 'bg-risk-medium-dim text-warn border-warn/30',
    high: 'bg-risk-high-dim text-high border-high/30',
    crit: 'bg-risk-critical-dim text-crit border-crit/30',
    info: 'bg-brand/12 text-brand border-brand/30',
    brand: 'bg-brand/12 text-brand border-brand/30',
    neutral: 'bg-ink-secondary/12 text-ink-secondary border-ink-secondary/30',
  };

  const displayIcon = icon ?? (showRiskIcon ? defaultIcon : null);

  return (
    <span
      className={cn(
        'inline-flex items-center gap-1.5 px-2.5 py-0.5 rounded-full text-xs font-medium border uppercase tracking-wider select-none shrink-0',
        variants[activeVariant],
        className
      )}
      {...props}
    >
      {displayIcon && <span className="shrink-0" aria-hidden="true">{displayIcon}</span>}
      <span>{children ?? (risk ? risk.toUpperCase() : '')}</span>
    </span>
  );
};
