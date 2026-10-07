import React from 'react';
import type { LucideIcon } from 'lucide-react';
import { cn } from '../../lib/utils';
import { Tooltip } from '../ui/Tooltip';

export interface NavItemProps {
  icon: LucideIcon;
  label: string;
  to: string;
  badge?: number;
  live?: boolean; // pulsing dot (running executions)
  dot?: boolean; // status dot for connections
  statusDot?: boolean; // alias for dot
  collapsed?: boolean;
  active?: boolean;
  onClick?: () => void;
}

export const NavItem: React.FC<NavItemProps> = ({
  icon: Icon,
  label,
  to,
  badge,
  live,
  dot,
  statusDot,
  collapsed = false,
  active = false,
  onClick,
}) => {
  const isHealthyDot = dot ?? statusDot;
  const href = to.startsWith('#') ? to : `#${to.startsWith('/') ? to : '/' + to}`;

  const link = (
    <a
      href={href}
      onClick={(e) => {
        if (onClick) {
          e.preventDefault();
          onClick();
        }
      }}
      aria-current={active ? 'page' : undefined}
      aria-label={collapsed ? label : undefined}
      data-testid={`nav-item-${label.toLowerCase().replace(/\s+/g, '-')}`}
      className={cn(
        'group relative mx-2 flex h-10 items-center gap-2.5 rounded-lg px-2.5 cursor-pointer select-none',
        'text-[13.5px] font-medium outline-none transition-colors duration-150',
        'focus-visible:ring-2 focus-visible:ring-brand focus-visible:ring-offset-0',
        active
          ? 'bg-nav-active text-brand-text font-semibold'
          : 'text-nav-icon hover:bg-nav-hover hover:text-ink-primary',
        collapsed && 'justify-center px-0 w-10 mx-auto'
      )}
    >
      {/* 2px x 20px rounded left indicator */}
      {active && (
        <span
          className="absolute left-0 top-1/2 h-5 w-0.5 -translate-y-1/2 rounded-full bg-brand-text"
          aria-hidden="true"
          data-testid="nav-active-indicator"
        />
      )}

      <Icon size={18} aria-hidden="true" className="shrink-0" />

      {!collapsed && <span className="truncate">{label}</span>}

      {!collapsed && live && (
        <span
          className="ml-auto h-2 w-2 animate-pulse rounded-full bg-ok shrink-0"
          aria-hidden="true"
        />
      )}

      {!collapsed && isHealthyDot !== undefined && (
        <span
          className={cn(
            'ml-auto h-2 w-2 rounded-full shrink-0',
            isHealthyDot ? 'bg-ok' : 'bg-crit'
          )}
          aria-hidden="true"
        />
      )}

      {!collapsed && badge !== undefined && badge > 0 && (
        <span className="ml-auto rounded-full bg-badge px-2 py-0.5 font-mono text-[11px] text-ink-secondary shrink-0">
          {badge}
        </span>
      )}
    </a>
  );

  if (collapsed) {
    return (
      <Tooltip
        side="right"
        content={label}
        wrapperClassName="w-full flex justify-center"
      >
        {link}
      </Tooltip>
    );
  }

  return link;
};

export default NavItem;
