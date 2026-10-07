import React, { useEffect } from 'react';
import {
  Sparkles,
  Files,
  Terminal,
  History,
  Plug,
  Settings,
  PanelLeftClose,
  PanelLeftOpen,
} from 'lucide-react';
import { NavItem } from '../nav/NavItem';
import { NavSection } from '../nav/NavSection';
import { Tooltip } from '../ui/Tooltip';
import { cn } from '../../lib/utils';

export type NavView = 'designer' | 'plans' | 'executions' | 'audit' | 'connections' | 'settings';

export function EnvChip({ env = 'local' }: { env?: string }) {
  return (
    <div
      data-testid="env-chip"
      className="flex items-center gap-1.5 px-2 py-0.5 rounded bg-badge text-ink-secondary text-[11px] font-mono border border-line select-none"
    >
      <span className="text-ink-tertiary">env:</span>
      <span className="text-ink-primary font-semibold">{env}</span>
    </div>
  );
}

export interface SidebarProps {
  activeView: NavView;
  onSelectView: (view: NavView) => void;
  collapsed: boolean;
  onToggleCollapse: () => void;
  plansCount?: number;
  isExecutionRunning?: boolean;
  isTargetHealthy?: boolean;
  environment?: string;
}

export const Sidebar: React.FC<SidebarProps> = ({
  activeView,
  onSelectView,
  collapsed,
  onToggleCollapse,
  plansCount = 0,
  isExecutionRunning = false,
  isTargetHealthy = true,
  environment = 'local',
}) => {
  // Global shortcut: Ctrl+B or ⌘B toggles sidebar collapse
  useEffect(() => {
    const handleKeyDown = (e: KeyboardEvent) => {
      if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === 'b') {
        e.preventDefault();
        onToggleCollapse();
      }
    };
    window.addEventListener('keydown', handleKeyDown);
    return () => window.removeEventListener('keydown', handleKeyDown);
  }, [onToggleCollapse]);

  return (
    <aside
      className={cn(
        'flex shrink-0 flex-col border-r border-line bg-nav transition-all duration-150 z-30 select-none',
        collapsed ? 'w-16' : 'w-60'
      )}
      aria-label="Sidebar Navigation"
    >
      {/* Navigation Sections */}
      <div className="py-3 space-y-4 overflow-y-auto overflow-x-hidden flex-1">
        {/* WORKSPACE SECTION */}
        <NavSection label="Workspace" collapsed={collapsed}>
          <NavItem
            to="/designer"
            icon={Sparkles}
            label="Designer"
            collapsed={collapsed}
            active={activeView === 'designer'}
            onClick={() => onSelectView('designer')}
          />
          <NavItem
            to="/plans"
            icon={Files}
            label="Plans"
            badge={plansCount}
            collapsed={collapsed}
            active={activeView === 'plans'}
            onClick={() => onSelectView('plans')}
          />
          <NavItem
            to="/executions"
            icon={Terminal}
            label="Executions"
            badge={isExecutionRunning ? 1 : undefined}
            live={isExecutionRunning}
            collapsed={collapsed}
            active={activeView === 'executions'}
            onClick={() => onSelectView('executions')}
          />
          <NavItem
            to="/audit"
            icon={History}
            label="Audit Trail"
            collapsed={collapsed}
            active={activeView === 'audit'}
            onClick={() => onSelectView('audit')}
          />
        </NavSection>

        {/* SYSTEM SECTION */}
        <NavSection label="System" collapsed={collapsed}>
          <NavItem
            to="/connections"
            icon={Plug}
            label="Connections"
            dot={isTargetHealthy}
            collapsed={collapsed}
            active={activeView === 'connections'}
            onClick={() => onSelectView('connections')}
          />
          <NavItem
            to="/settings"
            icon={Settings}
            label="Settings"
            collapsed={collapsed}
            active={activeView === 'settings'}
            onClick={() => onSelectView('settings')}
          />
        </NavSection>
      </div>

      {/* FOOTER ROW */}
      <div
        className={cn(
          'mt-auto flex items-center border-t border-line px-3 py-2 shrink-0',
          collapsed ? 'justify-center' : 'justify-between'
        )}
      >
        {!collapsed && <EnvChip env={environment} />}

        <Tooltip
          side={collapsed ? 'right' : 'top'}
          content={collapsed ? 'Expand (Ctrl+B)' : 'Collapse (Ctrl+B)'}
        >
          <button
            type="button"
            onClick={onToggleCollapse}
            aria-label={collapsed ? 'Expand (Ctrl+B)' : 'Collapse (Ctrl+B)'}
            data-testid="sidebar-toggle-btn"
            className="p-1.5 rounded-lg text-ink-secondary hover:text-ink-primary hover:bg-nav-hover transition-colors cursor-pointer focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand"
          >
            {collapsed ? (
              <PanelLeftOpen size={18} aria-hidden="true" />
            ) : (
              <PanelLeftClose size={18} aria-hidden="true" />
            )}
          </button>
        </Tooltip>
      </div>
    </aside>
  );
};

export default Sidebar;
