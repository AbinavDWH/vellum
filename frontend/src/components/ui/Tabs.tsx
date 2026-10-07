import React from 'react';
import { cn } from '../../lib/utils';

export interface TabItem {
  id: string;
  label: string;
  icon?: React.ReactNode;
  badge?: React.ReactNode;
}

export interface TabsProps {
  tabs: TabItem[];
  activeTab: string;
  onChange: (tabId: string) => void;
  variant?: 'line' | 'pills';
  className?: string;
}

export const Tabs: React.FC<TabsProps> = ({
  tabs,
  activeTab,
  onChange,
  variant = 'line',
  className,
}) => {
  return (
    <div
      role="tablist"
      className={cn(
        variant === 'line'
          ? 'flex items-center gap-6 border-b border-line overflow-x-auto scrollbar-none'
          : 'flex items-center gap-1.5 p-1 bg-surface border border-line rounded-lg overflow-x-auto scrollbar-none',
        className
      )}
    >
      {tabs.map((tab) => {
        const isActive = activeTab === tab.id;
        return (
          <button
            key={tab.id}
            role="tab"
            aria-selected={isActive}
            onClick={() => onChange(tab.id)}
            className={cn(
              'inline-flex items-center gap-2 whitespace-nowrap text-xs font-medium transition-colors cursor-pointer focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand focus-visible:ring-offset-1 select-none',
              variant === 'line'
                ? cn(
                    'py-3 border-b-2 font-semibold',
                    isActive
                      ? 'border-brand text-brand'
                      : 'border-transparent text-ink-secondary hover:text-ink-primary hover:border-line'
                  )
                : cn(
                    'px-3 py-1.5 rounded-md font-medium',
                    isActive
                      ? 'bg-elevated text-ink-primary shadow-sm border border-line'
                      : 'text-ink-secondary hover:text-ink-primary hover:bg-elevated/50'
                  )
            )}
          >
            {tab.icon && <span className="shrink-0" aria-hidden="true">{tab.icon}</span>}
            <span>{tab.label}</span>
            {tab.badge && <span className="shrink-0">{tab.badge}</span>}
          </button>
        );
      })}
    </div>
  );
};
