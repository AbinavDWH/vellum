import React, { useState, useEffect, useRef } from 'react';
import {
  X,
  Search,
  Plus,
  MessageSquare,
  Edit2,
  Trash2,
  Check,
  Clock,
  CheckCircle2,
  AlertCircle,
  Sparkles,
} from 'lucide-react';
import { ChatSession } from '../../types';
import { cn } from '../../lib/utils';

export interface SessionDrawerProps {
  isOpen: boolean;
  onClose: () => void;
  sessions: ChatSession[];
  currentSessionId?: string | null;
  onSelectSession: (sessionId: string) => void;
  onNewChat: () => void;
  onRenameSession: (sessionId: string, newTitle: string) => Promise<void>;
  onDeleteSession: (sessionId: string) => Promise<void>;
  onSearchChange: (search: string) => void;
}

export const SessionDrawer: React.FC<SessionDrawerProps> = ({
  isOpen,
  onClose,
  sessions,
  currentSessionId,
  onSelectSession,
  onNewChat,
  onRenameSession,
  onDeleteSession,
  onSearchChange,
}) => {
  const [searchTerm, setSearchTerm] = useState('');
  const [editingSessionId, setEditingSessionId] = useState<string | null>(null);
  const [editingTitle, setEditingTitle] = useState('');

  const onSearchChangeRef = useRef(onSearchChange);
  useEffect(() => {
    onSearchChangeRef.current = onSearchChange;
  }, [onSearchChange]);

  useEffect(() => {
    if (!isOpen) {
      if (searchTerm) setSearchTerm('');
      return;
    }
    const timer = setTimeout(() => {
      onSearchChangeRef.current(searchTerm);
    }, 250);
    return () => clearTimeout(timer);
  }, [searchTerm, isOpen]);

  const handleStartRename = (e: React.MouseEvent, s: ChatSession) => {
    e.stopPropagation();
    setEditingSessionId(s.id);
    setEditingTitle(s.title);
  };

  const handleSaveRename = async (e: React.MouseEvent | React.FormEvent, sId: string) => {
    e.stopPropagation();
    e.preventDefault();
    if (editingTitle.trim()) {
      await onRenameSession(sId, editingTitle.trim());
    }
    setEditingSessionId(null);
  };

  const handleDelete = async (e: React.MouseEvent, sId: string) => {
    e.stopPropagation();
    if (confirm('Delete this conversation history? Audit logs remain preserved.')) {
      await onDeleteSession(sId);
    }
  };

  const formatRelativeTime = (timestamp: string) => {
    if (!timestamp) return '';
    try {
      const date = new Date(timestamp);
      const now = new Date();
      const diffMs = now.getTime() - date.getTime();
      const diffMins = Math.floor(diffMs / (1000 * 60));
      const diffHours = Math.floor(diffMs / (1000 * 60 * 60));
      const diffDays = Math.floor(diffMs / (1000 * 60 * 60 * 24));

      if (diffMins < 1) return 'Just now';
      if (diffMins < 60) return `${diffMins}m ago`;
      if (diffHours < 24) return `${diffHours}h ago`;
      if (diffDays === 1) return 'Yesterday';
      if (diffDays < 7) return `${diffDays}d ago`;
      return date.toLocaleDateString([], { month: 'short', day: 'numeric' });
    } catch {
      return '';
    }
  };

  const getStatusDot = (status: string) => {
    if (status === 'completed' || status === 'has-completed-plan') {
      return <span className="h-2 w-2 rounded-full bg-emerald-400 shrink-0" title="Has completed plan" />;
    }
    if (status === 'failed') {
      return <span className="h-2 w-2 rounded-full bg-rose-500 shrink-0" title="Plan execution failed" />;
    }
    return <span className="h-2 w-2 rounded-full bg-brand shrink-0" title="Active session" />;
  };

  if (!isOpen) return null;

  return (
    <div className="fixed inset-0 z-50 flex">
      {/* Backdrop */}
      <div
        className="fixed inset-0 bg-black/60 backdrop-blur-xs transition-opacity"
        onClick={onClose}
      />

      {/* Drawer Panel */}
      <div className="relative w-80 max-w-[85vw] h-full bg-surface border-r border-line shadow-2xl flex flex-col z-10 animate-in slide-in-from-left duration-200">
        {/* Header */}
        <div className="p-4 border-b border-line flex items-center justify-between">
          <div className="flex items-center gap-2">
            <MessageSquare className="h-4 w-4 text-brand" />
            <h3 className="text-sm font-semibold text-ink-primary">Chat History</h3>
          </div>
          <button
            onClick={onClose}
            className="p-1 rounded text-ink-tertiary hover:text-ink-primary hover:bg-elevated cursor-pointer"
          >
            <X className="h-4 w-4" />
          </button>
        </div>

        {/* Action Button: + New Chat */}
        <div className="p-3 border-b border-line">
          <button
            onClick={() => {
              onNewChat();
              onClose();
            }}
            className="w-full flex items-center justify-center gap-2 py-2 px-3 rounded-lg bg-brand/10 hover:bg-brand/20 border border-brand/30 text-brand text-xs font-semibold cursor-pointer transition-colors shadow-xs"
          >
            <Plus className="h-3.5 w-3.5" />
            New Chat
          </button>
        </div>

        {/* Search */}
        <div className="p-3 border-b border-line">
          <div className="relative">
            <Search className="absolute left-2.5 top-2.5 h-3.5 w-3.5 text-ink-tertiary" />
            <input
              type="text"
              placeholder="Search conversations..."
              value={searchTerm}
              onChange={(e) => setSearchTerm(e.target.value)}
              className="w-full pl-8 pr-3 py-1.5 bg-canvas border border-line rounded-md text-xs text-ink-primary placeholder:text-ink-tertiary focus:outline-hidden focus:border-brand"
            />
          </div>
        </div>

        {/* Session List */}
        <div className="flex-1 overflow-y-auto p-2 space-y-1">
          {sessions.length === 0 ? (
            <div className="h-48 flex flex-col items-center justify-center text-center p-4 text-ink-secondary">
              <Sparkles className="h-6 w-6 text-ink-tertiary mb-2" />
              <p className="text-xs font-medium text-ink-secondary">No conversations yet</p>
              <p className="text-[11px] text-ink-tertiary mt-0.5">Start your first design.</p>
            </div>
          ) : (
            sessions.map((s) => {
              const isSelected = s.id === currentSessionId;
              const isEditing = editingSessionId === s.id;

              return (
                <div
                  key={s.id}
                  onClick={() => {
                    if (!isEditing) {
                      onSelectSession(s.id);
                      onClose();
                    }
                  }}
                  className={cn(
                    'group relative flex flex-col gap-1 p-2.5 rounded-lg border text-left cursor-pointer transition-all',
                    isSelected
                      ? 'bg-brand/10 border-brand/40 text-ink-primary'
                      : 'bg-surface hover:bg-elevated border-transparent hover:border-line text-ink-secondary'
                  )}
                >
                  <div className="flex items-center justify-between gap-1.5">
                    <div className="flex items-center gap-2 overflow-hidden flex-1">
                      {getStatusDot(s.status)}
                      {isEditing ? (
                        <form
                          onSubmit={(e) => handleSaveRename(e, s.id)}
                          className="flex items-center gap-1 w-full"
                          onClick={(e) => e.stopPropagation()}
                        >
                          <input
                            type="text"
                            value={editingTitle}
                            onChange={(e) => setEditingTitle(e.target.value)}
                            autoFocus
                            className="w-full text-xs font-medium bg-canvas border border-brand px-1.5 py-0.5 rounded text-ink-primary"
                          />
                          <button
                            type="submit"
                            className="p-1 text-brand hover:text-brand-accent"
                          >
                            <Check className="h-3 w-3" />
                          </button>
                        </form>
                      ) : (
                        <span
                          className={cn(
                            'text-xs font-medium truncate flex-1',
                            isSelected ? 'text-ink-primary font-semibold' : 'text-ink-secondary group-hover:text-ink-primary'
                          )}
                          title={s.title}
                        >
                          {s.title}
                        </span>
                      )}
                    </div>

                    {/* Actions on hover */}
                    {!isEditing && (
                      <div className="opacity-0 group-hover:opacity-100 flex items-center gap-1 transition-opacity">
                        <button
                          type="button"
                          onClick={(e) => handleStartRename(e, s)}
                          title="Rename session"
                          className="p-1 rounded text-ink-tertiary hover:text-ink-primary hover:bg-surface cursor-pointer"
                        >
                          <Edit2 className="h-3 w-3" />
                        </button>
                        <button
                          type="button"
                          onClick={(e) => handleDelete(e, s.id)}
                          title="Delete session"
                          className="p-1 rounded text-ink-tertiary hover:text-rose-400 hover:bg-surface cursor-pointer"
                        >
                          <Trash2 className="h-3 w-3" />
                        </button>
                      </div>
                    )}
                  </div>

                  {/* Metadata: time & message count */}
                  <div className="flex items-center justify-between text-[10px] text-ink-tertiary pl-4">
                    <span className="flex items-center gap-1">
                      <Clock className="h-2.5 w-2.5" />
                      {formatRelativeTime(s.updated_at || s.created_at)}
                    </span>
                    <span>{s.message_count} {s.message_count === 1 ? 'msg' : 'msgs'}</span>
                  </div>
                </div>
              );
            })
          )}
        </div>
      </div>
    </div>
  );
};
