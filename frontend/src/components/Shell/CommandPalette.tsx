import React, { useState, useEffect, useRef } from 'react';
import { Search, Sparkles, FolderKanban, Terminal, History, Server, Settings, ArrowRight, CornerDownLeft, X, Sun, Moon, PanelLeft } from 'lucide-react';
import { cn } from '../../lib/utils';
import { useTheme } from '../../context/ThemeContext';

export interface CommandItem {
  id: string;
  title: string;
  category: 'Navigation' | 'Plans' | 'Presets' | 'Actions';
  icon: React.ReactNode;
  hint?: string;
  action: () => void;
}

export interface CommandPaletteProps {
  isOpen: boolean;
  onClose: () => void;
  onNavigate: (view: string) => void;
  onSelectPrompt?: (prompt: string) => void;
  recentPlanIds?: string[];
  onSelectPlan?: (planId: string) => void;
  onToggleSidebar?: () => void;
}

export const CommandPalette: React.FC<CommandPaletteProps> = ({
  isOpen,
  onClose,
  onNavigate,
  onSelectPrompt,
  recentPlanIds = [],
  onSelectPlan,
  onToggleSidebar,
}) => {
  const { theme, toggleTheme } = useTheme();
  const [query, setQuery] = useState('');
  const [selectedIndex, setSelectedIndex] = useState(0);
  const inputRef = useRef<HTMLInputElement>(null);

  const baseItems: CommandItem[] = [
    {
      id: 'nav-designer',
      title: 'Infrastructure Designer',
      category: 'Navigation',
      icon: <Sparkles className="h-4 w-4 text-brand" />,
      hint: 'Jump to AI Chat & Workspace',
      action: () => {
        onNavigate('designer');
        onClose();
      },
    },
    {
      id: 'nav-plans',
      title: 'Plans & Architectures',
      category: 'Navigation',
      icon: <FolderKanban className="h-4 w-4 text-info" />,
      hint: 'View stored infrastructure plans',
      action: () => {
        onNavigate('plans');
        onClose();
      },
    },
    {
      id: 'nav-executions',
      title: 'Execution & Verification Console',
      category: 'Navigation',
      icon: <Terminal className="h-4 w-4 text-ok" />,
      hint: 'Live stream & drift status',
      action: () => {
        onNavigate('executions');
        onClose();
      },
    },
    {
      id: 'nav-audit',
      title: 'Immutable Audit Trail',
      category: 'Navigation',
      icon: <History className="h-4 w-4 text-warn" />,
      hint: 'Inspect SHA-256 verified event chain',
      action: () => {
        onNavigate('audit');
        onClose();
      },
    },
    {
      id: 'nav-connections',
      title: 'Environment & Connections',
      category: 'Navigation',
      icon: <Server className="h-4 w-4 text-high" />,
      hint: 'Cloud & AI Engine status',
      action: () => {
        onNavigate('connections');
        onClose();
      },
    },
    {
      id: 'nav-settings',
      title: 'System Settings',
      category: 'Navigation',
      icon: <Settings className="h-4 w-4 text-ink-secondary" />,
      hint: 'Preferences & token defaults',
      action: () => {
        onNavigate('settings');
        onClose();
      },
    },
    // Presets
    {
      id: 'preset-postgres',
      title: 'Preset: PostgreSQL RDS on AWS with S3',
      category: 'Presets',
      icon: <Sparkles className="h-4 w-4 text-brand" />,
      hint: 'High-availability private database & assets bucket',
      action: () => {
        onNavigate('designer');
        onSelectPrompt?.('I need a PostgreSQL database for a web platform with users and orders tables, deployed on AWS with an S3 bucket for assets.');
        onClose();
      },
    },
    {
      id: 'preset-vpc',
      title: 'Preset: Production AWS VPC & Subnets',
      category: 'Presets',
      icon: <Sparkles className="h-4 w-4 text-brand" />,
      hint: 'CIDR 10.0.0.0/16, public and private subnets in us-east-1',
      action: () => {
        onNavigate('designer');
        onSelectPrompt?.('Design an AWS VPC with CIDR 10.0.0.0/16, one public subnet in us-east-1a, and a private subnet for managed database.');
        onClose();
      },
    },
    {
      id: 'preset-s3',
      title: 'Preset: Versioned S3 Bucket for Assets',
      category: 'Presets',
      icon: <Sparkles className="h-4 w-4 text-brand" />,
      hint: 'vellum-app-assets with versioning and security policy',
      action: () => {
        onNavigate('designer');
        onSelectPrompt?.('Create an S3 bucket called vellum-app-assets on AWS with versioning enabled and encrypted at rest.');
        onClose();
      },
    },
    // Actions
    {
      id: 'action-theme-toggle',
      title: `Switch Theme (${theme === 'dark' ? 'Light' : 'Dark'} Mode)`,
      category: 'Actions',
      icon: theme === 'dark' ? <Sun className="h-4 w-4 text-brand" /> : <Moon className="h-4 w-4 text-brand-text" />,
      hint: 'Toggle between dark and light palette',
      action: () => {
        toggleTheme();
        onClose();
      },
    },
    {
      id: 'action-sidebar-toggle',
      title: 'Toggle Sidebar Navigation',
      category: 'Actions',
      icon: <PanelLeft className="h-4 w-4 text-ink-secondary" />,
      hint: 'Collapse or expand navigation rail (Ctrl+B / ⌘B)',
      action: () => {
        onToggleSidebar?.();
        onClose();
      },
    },
  ];

  // Add recent plan items
  const planItems: CommandItem[] = recentPlanIds.map((pid) => ({
    id: `plan-${pid}`,
    title: `Jump to Plan: ${pid}`,
    category: 'Plans',
    icon: <FolderKanban className="h-4 w-4 text-brand" />,
    hint: 'Open in Designer',
    action: () => {
      onSelectPlan?.(pid);
      onNavigate('designer');
      onClose();
    },
  }));

  const allItems = [...baseItems, ...planItems];

  const filteredItems = allItems.filter((item) => {
    if (!query.trim()) return true;
    const q = query.toLowerCase();
    return (
      item.title.toLowerCase().includes(q) ||
      item.category.toLowerCase().includes(q) ||
      (item.hint && item.hint.toLowerCase().includes(q))
    );
  });

  useEffect(() => {
    if (isOpen) {
      setQuery('');
      setSelectedIndex(0);
      setTimeout(() => inputRef.current?.focus(), 50);
    }
  }, [isOpen]);

  useEffect(() => {
    setSelectedIndex(0);
  }, [query]);

  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === 'ArrowDown') {
      e.preventDefault();
      setSelectedIndex((prev) => (prev + 1) % (filteredItems.length || 1));
    } else if (e.key === 'ArrowUp') {
      e.preventDefault();
      setSelectedIndex((prev) => (prev - 1 + filteredItems.length) % (filteredItems.length || 1));
    } else if (e.key === 'Enter') {
      e.preventDefault();
      if (filteredItems[selectedIndex]) {
        filteredItems[selectedIndex].action();
      }
    } else if (e.key === 'Escape') {
      e.preventDefault();
      onClose();
    }
  };

  if (!isOpen) return null;

  return (
    <div
      className="fixed inset-0 z-50 flex items-start justify-center pt-20 p-4 bg-base/80 backdrop-blur-sm animate-in fade-in duration-150"
      onClick={onClose}
      role="dialog"
      aria-modal="true"
      aria-label="Command Palette"
    >
      <div
        className="w-full max-w-xl bg-elevated border border-line rounded-2xl shadow-modal overflow-hidden flex flex-col"
        onClick={(e) => e.stopPropagation()}
        onKeyDown={handleKeyDown}
      >
        {/* Search input header */}
        <div className="flex items-center gap-3 px-4 py-3.5 border-b border-line bg-surface">
          <Search className="h-4 w-4 text-ink-secondary shrink-0" aria-hidden="true" />
          <input
            ref={inputRef}
            type="text"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            placeholder="Type a command, plan ID, or preset prompt..."
            className="flex-1 bg-transparent text-sm text-ink-primary placeholder-ink-tertiary focus:outline-none"
            aria-autocomplete="list"
          />
          {query && (
            <button
              onClick={() => setQuery('')}
              className="p-1 rounded text-ink-secondary hover:text-ink-primary"
              aria-label="Clear query"
            >
              <X className="h-3.5 w-3.5" />
            </button>
          )}
          <kbd className="hidden sm:inline-block px-1.5 py-0.5 text-[10px] font-mono text-ink-secondary bg-elevated border border-line rounded">
            ESC
          </kbd>
        </div>

        {/* List of items */}
        <div className="max-h-80 overflow-y-auto p-2 divide-y divide-transparent">
          {filteredItems.length === 0 ? (
            <div className="py-8 text-center text-xs text-ink-secondary">
              No matching commands or plans found.
            </div>
          ) : (
            filteredItems.map((item, idx) => {
              const isSelected = idx === selectedIndex;
              return (
                <div
                  key={item.id}
                  onClick={() => item.action()}
                  onMouseEnter={() => setSelectedIndex(idx)}
                  className={cn(
                    'flex items-center justify-between px-3 py-2.5 rounded-lg text-xs cursor-pointer transition-colors select-none',
                    isSelected
                      ? 'bg-brand/10 text-brand'
                      : 'text-ink-primary hover:bg-surface'
                  )}
                >
                  <div className="flex items-center gap-3 min-w-0">
                    <span className="shrink-0">{item.icon}</span>
                    <div className="min-w-0">
                      <div className="font-medium truncate">{item.title}</div>
                      {item.hint && (
                        <div className="text-[11px] text-ink-secondary truncate">{item.hint}</div>
                      )}
                    </div>
                  </div>
                  <div className="flex items-center gap-2 shrink-0 ml-3">
                    <span className="text-[10px] uppercase font-mono px-1.5 py-0.5 rounded bg-surface border border-line text-ink-tertiary">
                      {item.category}
                    </span>
                    {isSelected && <CornerDownLeft className="h-3.5 w-3.5 text-brand" />}
                  </div>
                </div>
              );
            })
          )}
        </div>

        {/* Footer shortcuts */}
        <div className="flex items-center justify-between px-4 py-2 text-[11px] text-ink-tertiary bg-surface border-t border-line">
          <div className="flex items-center gap-3">
            <span>
              <kbd className="font-mono bg-elevated px-1 py-0.5 rounded border border-line text-ink-secondary">↑</kbd>{' '}
              <kbd className="font-mono bg-elevated px-1 py-0.5 rounded border border-line text-ink-secondary">↓</kbd> Navigate
            </span>
            <span>
              <kbd className="font-mono bg-elevated px-1 py-0.5 rounded border border-line text-ink-secondary">↵</kbd> Select
            </span>
          </div>
          <span>Vellum Command Plane</span>
        </div>
      </div>
    </div>
  );
};
