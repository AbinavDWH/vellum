import React, { useState, useRef, useEffect } from 'react';
import {
  Send,
  Sparkles,
  Database,
  Cloud,
  Layers,
  Loader2,
  HelpCircle,
  ArrowRight,
  User,
  Trash2,
  Brain,
  History,
  Plus,
  FileText,
  Code,
  Eye,
  Square,
} from 'lucide-react';
import { ClarificationResponse, RagCitation } from '../../types';
import { Button, MarkdownRenderer, CopyButton } from '../ui';
import { cn } from '../../lib/utils';

export interface ChatMessage {
  id: string;
  sender: 'user' | 'assistant';
  text: string;
  timestamp: string;
  clarification?: ClarificationResponse;
  rag_citations?: RagCitation[];
  requirements_md?: string;
}

export interface ChatPaneProps {
  messages: ChatMessage[];
  onSendMessage: (prompt: string) => void;
  isLoading: boolean;
  onCancelChat?: () => void;
  onSelectPreset?: (prompt: string) => void;
  onClearHistory?: () => void;
  onOpenHistory?: () => void;
  onNewChat?: () => void;
  sessionTitle?: string;
  onSynthesizePlan?: () => void;
  requirementsMd?: string;
}

const PRESET_TEMPLATES = [
  {
    label: 'PostgreSQL + AWS S3',
    prompt:
      'I need a PostgreSQL database for an e-commerce platform with users and orders tables, deployed on AWS with an S3 bucket for invoices.',
    icon: Database,
  },
  {
    label: 'S3 Assets Bucket',
    prompt: 'Create an S3 bucket called vellum-app-assets on AWS with versioning enabled.',
    icon: Cloud,
  },
  {
    label: 'VPC & Subnets',
    prompt:
      'Design an AWS VPC with CIDR 10.0.0.0/16, one public subnet in us-east-1a, and a private subnet for managed database.',
    icon: Layers,
  },
];

export const ChatPane: React.FC<ChatPaneProps> = ({
  messages,
  onSendMessage,
  isLoading,
  onCancelChat,
  onClearHistory,
  onOpenHistory,
  onNewChat,
  sessionTitle,
  onSynthesizePlan,
  requirementsMd,
}) => {
  const [inputPrompt, setInputPrompt] = useState('');
  const [clarificationAnswers, setClarificationAnswers] = useState<Record<string, Record<number, string>>>({});
  const [rawMessageIds, setRawMessageIds] = useState<Record<string, boolean>>({});
  const messagesEndRef = useRef<HTMLDivElement>(null);
  const textareaRef = useRef<HTMLTextAreaElement>(null);

  const toggleRawMode = (messageId: string) => {
    setRawMessageIds((prev) => ({
      ...prev,
      [messageId]: !prev[messageId],
    }));
  };

  // Auto-scroll chat to bottom
  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [messages, isLoading]);

  // Adjust textarea height automatically
  const handleTextareaChange = (e: React.ChangeEvent<HTMLTextAreaElement>) => {
    setInputPrompt(e.target.value);
    if (textareaRef.current) {
      textareaRef.current.style.height = 'auto';
      textareaRef.current.style.height = `${Math.min(textareaRef.current.scrollHeight, 180)}px`;
    }
  };

  const handleKeyDown = (e: React.KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      handleSubmit();
    }
  };

  const handleSubmit = () => {
    if (!inputPrompt.trim() || isLoading) return;
    const text = inputPrompt.trim();
    setInputPrompt('');
    if (textareaRef.current) {
      textareaRef.current.style.height = 'auto';
    }
    onSendMessage(text);
  };

  const handleAnswerChange = (messageId: string, questionIdx: number, val: string) => {
    setClarificationAnswers((prev) => ({
      ...prev,
      [messageId]: {
        ...(prev[messageId] || {}),
        [questionIdx]: val,
      },
    }));
  };

  const handleClarificationSubmit = (messageId: string, clarification: ClarificationResponse) => {
    const answers = clarificationAnswers[messageId] || {};
    const formatted: string[] = [];
    clarification.questions.forEach((q, idx) => {
      const ans = answers[idx] ?? q.default_suggestion ?? '';
      if (ans.trim()) {
        formatted.push(`- **${q.question}**: ${ans.trim()}`);
      }
    });
    if (formatted.length === 0) return;
    const combined = `Please apply the following architecture decisions:\n${formatted.join('\n')}`;
    onSendMessage(combined);
  };

  return (
    <div className="flex flex-col h-full bg-surface border-r border-line">
      {/* Chat header */}
      <div className="px-3 py-2.5 border-b border-line flex items-center justify-between shrink-0 bg-surface/50 gap-2">
        <div className="flex items-center gap-2 min-w-0">
          <div className="h-6 w-6 rounded-md bg-brand/10 border border-brand/30 flex items-center justify-center text-brand shrink-0">
            <Sparkles className="h-3.5 w-3.5" aria-hidden="true" />
          </div>
          <div className="truncate">
            <h2 className="text-xs font-semibold text-ink-primary truncate" title={sessionTitle || 'Architect AI Assistant'}>
              {sessionTitle || 'Architect AI Assistant'}
            </h2>
            <p className="text-[10px] text-ink-secondary">Conversational Cloud Architect & requirements.md</p>
          </div>
        </div>

        <div className="flex items-center gap-1.5 shrink-0">
          {onSynthesizePlan && (
            <button
              type="button"
              onClick={onSynthesizePlan}
              disabled={isLoading}
              title="Synthesize infrastructure plan from stored requirements specification"
              className="flex items-center gap-1 text-[11px] px-2 py-1 rounded bg-brand/20 hover:bg-brand/30 border border-brand/40 text-brand font-medium transition-colors cursor-pointer disabled:opacity-50"
            >
              <Sparkles className="h-3 w-3" />
              <span>Synthesize</span>
            </button>
          )}

          {onOpenHistory && (
            <button
              type="button"
              onClick={onOpenHistory}
              title="Chat History"
              className="flex items-center gap-1 text-[11px] px-2 py-1 rounded bg-elevated hover:bg-elevated/80 border border-line text-ink-secondary hover:text-ink-primary transition-colors cursor-pointer"
            >
              <History className="h-3 w-3" />
              <span>History</span>
            </button>
          )}

          {onNewChat && (
            <button
              type="button"
              onClick={onNewChat}
              title="New Chat Session"
              className="flex items-center gap-1 text-[11px] px-2 py-1 rounded bg-brand/15 hover:bg-brand/25 border border-brand/30 text-brand font-medium transition-colors cursor-pointer"
            >
              <Plus className="h-3 w-3" />
              <span>New Chat</span>
            </button>
          )}

          {onClearHistory && messages.length > 0 && (
            <button
              type="button"
              onClick={onClearHistory}
              title="Clear conversation history"
              className="text-ink-tertiary hover:text-crit transition-colors p-1 rounded hover:bg-elevated cursor-pointer"
            >
              <Trash2 className="h-3.5 w-3.5" />
            </button>
          )}
        </div>
      </div>

      {/* Message Thread */}
      <div
        className="flex-1 overflow-y-auto p-4 space-y-4"
        role="log"
        aria-live="polite"
        aria-label="Conversation with Vellum Architect"
      >
        {messages.length === 0 ? (
          <div className="h-full flex flex-col items-center justify-center text-center p-6 text-ink-secondary space-y-3">
            <div className="h-10 w-10 rounded-xl bg-elevated border border-line flex items-center justify-center text-brand">
              <Sparkles className="h-5 w-5" />
            </div>
            <div>
              <p className="text-sm font-semibold text-ink-primary">Chat with Vellum Cloud Architect</p>
              <p className="text-xs text-ink-secondary mt-1 max-w-xs leading-relaxed">
                Describe your workload, database needs, or ask architecture questions. Vellum maintains a living <span className="font-mono text-brand font-semibold">requirements.md</span> specification and synthesizes plans when ready.
              </p>
            </div>
          </div>
        ) : (
          messages.map((msg) => {
            const isUser = msg.sender === 'user';

            return (
              <div
                key={msg.id}
                className={cn('flex flex-col gap-1', isUser ? 'items-end' : 'items-start')}
              >
                <div className="flex items-center justify-between gap-2 text-[10px] text-ink-tertiary px-1 w-full max-w-[88%]">
                  <div className="flex items-center gap-1.5 min-w-0 truncate">
                    {!isUser && (
                      <div className="h-4 w-4 rounded-full bg-brand/20 text-brand flex items-center justify-center shrink-0">
                        <Sparkles className="h-2.5 w-2.5" />
                      </div>
                    )}
                    <span className="font-medium text-ink-secondary">{isUser ? 'You' : 'Vellum Architect'}</span>
                    <span>•</span>
                    <span>{new Date(msg.timestamp).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })}</span>
                  </div>

                  {!isUser && (
                    <div className="flex items-center gap-1.5 shrink-0">
                      <button
                        type="button"
                        onClick={() => toggleRawMode(msg.id)}
                        className="inline-flex items-center gap-1 px-1.5 py-0.5 rounded bg-base/80 hover:bg-base border border-line text-[10px] text-ink-secondary hover:text-ink-primary transition-colors cursor-pointer"
                        title={rawMessageIds[msg.id] ? 'Switch to formatted view' : 'Show raw markdown response'}
                      >
                        {rawMessageIds[msg.id] ? (
                          <>
                            <Eye className="h-2.5 w-2.5 text-brand" />
                            <span>Formatted</span>
                          </>
                        ) : (
                          <>
                            <Code className="h-2.5 w-2.5 text-ink-tertiary" />
                            <span>Raw Response</span>
                          </>
                        )}
                      </button>
                      <CopyButton value={msg.text} label="Copy" className="text-[10px] py-0.5 px-1.5 h-auto" />
                    </div>
                  )}
                </div>

                <div
                  className={cn(
                    'max-w-[88%] rounded-xl px-4 py-2.5 text-xs leading-relaxed transition-colors',
                    isUser
                      ? 'bg-brand/15 text-ink-primary border border-brand/30 rounded-tr-none'
                      : 'bg-elevated text-ink-primary border border-line rounded-tl-none'
                  )}
                >
                  {isUser ? (
                    <p className="whitespace-pre-wrap">{msg.text}</p>
                  ) : rawMessageIds[msg.id] ? (
                    <div className="space-y-1.5">
                      <div className="flex items-center justify-between text-[10px] text-ink-tertiary border-b border-line/60 pb-1 mb-1">
                        <span className="font-mono text-brand font-semibold">raw_response.md</span>
                        <span>Raw Markdown Source</span>
                      </div>
                      <pre className="p-2.5 bg-base/90 border border-line rounded-lg font-mono text-[11px] leading-relaxed whitespace-pre-wrap select-text text-ink-secondary overflow-x-auto">
                        {msg.text}
                      </pre>
                    </div>
                  ) : (
                    <MarkdownRenderer content={msg.text} />
                  )}

                  {/* Grounded RAG Citations */}
                  {msg.rag_citations && msg.rag_citations.length > 0 && (
                    <div className="mt-2.5 pt-2 border-t border-line/60 space-y-1.5">
                      <div className="flex items-center gap-1.5 text-[10px] text-brand font-medium">
                        <Brain className="h-3 w-3" />
                        <span>Grounded via {msg.rag_citations.length} authoritative specification{msg.rag_citations.length > 1 ? 's' : ''}:</span>
                      </div>
                      <div className="flex flex-wrap gap-1.5">
                        {msg.rag_citations.map((cite, cIdx) => (
                          <span
                            key={cIdx}
                            title={`Score: ${cite.score} | Domain: ${cite.domain}`}
                            className="inline-flex items-center gap-1 px-1.5 py-0.5 rounded bg-base border border-line text-[10px] text-ink-secondary"
                          >
                            <span className="font-mono text-brand font-semibold">{cite.tag}</span>
                            <span className="truncate max-w-[170px]">{cite.title}</span>
                          </span>
                        ))}
                      </div>
                    </div>
                  )}

                  {/* Interactive Architecture Decisions & Conflict Resolution Card */}
                  {msg.clarification &&
                    msg.clarification.questions &&
                    msg.clarification.questions.length > 0 && (
                    <div className="mt-3 pt-3 border-t border-line space-y-3">
                      <div className="flex items-center gap-1.5 text-brand font-semibold text-xs">
                        <HelpCircle className="h-4 w-4 shrink-0" />
                        <span>
                          {msg.clarification.questions.some((q) => q.conflict_type)
                            ? 'Pre-Flight Conflict Resolution:'
                            : 'Architecture Decisions & Interactive Choices:'}
                        </span>
                      </div>

                      <div className="space-y-2.5">
                        {msg.clarification.questions.map((q, qIdx) => {
                          const answers = clarificationAnswers[msg.id] || {};
                          const currentVal = answers[qIdx] ?? q.default_suggestion ?? '';

                          return (
                            <div
                              key={qIdx}
                              className="p-2.5 rounded-lg bg-base border border-line space-y-1.5"
                            >
                              <label className="block text-[11px] font-semibold text-ink-primary">
                                {qIdx + 1}. {q.question}
                              </label>
                              {q.context && (
                                <p className="text-[10px] text-ink-secondary leading-snug">
                                  {q.context}
                                </p>
                              )}
                              {q.options && q.options.length > 0 ? (
                                <div className="flex flex-wrap gap-1.5 pt-1">
                                  {q.options.map((opt, oIdx) => {
                                    const isSelected = currentVal === opt;
                                    return (
                                      <button
                                        key={oIdx}
                                        type="button"
                                        onClick={() => handleAnswerChange(msg.id, qIdx, opt)}
                                        className={cn(
                                          'px-2.5 py-1 rounded-md text-[11px] font-medium border transition-all text-left cursor-pointer',
                                          isSelected
                                            ? 'bg-brand/20 border-brand text-brand ring-1 ring-brand font-semibold'
                                            : 'bg-elevated border-line text-ink-secondary hover:border-line/80 hover:text-ink-primary'
                                        )}
                                      >
                                        {opt}
                                      </button>
                                    );
                                  })}
                                </div>
                              ) : (
                                <input
                                  type="text"
                                  value={currentVal}
                                  onChange={(e) => handleAnswerChange(msg.id, qIdx, e.target.value)}
                                  placeholder={q.default_suggestion || 'Type response...'}
                                  className="w-full bg-elevated border border-line rounded px-2.5 py-1.5 text-xs text-ink-primary focus:outline-none focus:ring-1 focus:ring-brand font-sans"
                                />
                              )}
                            </div>
                          );
                        })}
                      </div>

                      <div className="flex justify-end pt-1">
                        <Button
                          variant="primary"
                          size="sm"
                          disabled={isLoading}
                          onClick={() => handleClarificationSubmit(msg.id, msg.clarification!)}
                          rightIcon={<ArrowRight className="h-3 w-3" />}
                        >
                          {msg.clarification.questions.some((q) => q.conflict_type)
                            ? 'Submit Resolution & Continue'
                            : 'Apply Architecture Choices & Continue'}
                        </Button>
                      </div>
                    </div>
                  )}
                </div>
              </div>
            );
          })
        )}

        {/* Typing indicator pulse */}
        {isLoading && (
          <div className="flex items-start gap-2">
            <div className="h-5 w-5 rounded-full bg-brand/20 text-brand flex items-center justify-center shrink-0 mt-0.5">
              <Sparkles className="h-3 w-3 animate-spin" />
            </div>
            <div className="px-3.5 py-2 rounded-xl bg-elevated border border-line flex items-center gap-2 text-ink-secondary">
              <span className="h-1.5 w-1.5 rounded-full bg-brand animate-pulse" />
              <span className="h-1.5 w-1.5 rounded-full bg-brand animate-pulse [animation-delay:0.2s]" />
              <span className="h-1.5 w-1.5 rounded-full bg-brand animate-pulse [animation-delay:0.4s]" />
              <span className="text-[11px] text-ink-tertiary ml-1">Synthesizing architecture plan...</span>
              {onCancelChat && (
                <button
                  type="button"
                  onClick={onCancelChat}
                  className="ml-2 text-[10px] font-semibold text-crit hover:underline cursor-pointer flex items-center gap-1"
                >
                  <Square className="h-2.5 w-2.5 fill-current" />
                  Cancel
                </button>
              )}
            </div>
          </div>
        )}

        <div ref={messagesEndRef} />
      </div>

      {/* Preset Chips & Input Footer */}
      <div className="p-3 border-t border-line bg-surface/80 space-y-2 shrink-0">
        {/* Presets */}
        <div className="flex items-center gap-1.5 overflow-x-auto scrollbar-none pb-1">
          <span className="text-[10px] text-ink-tertiary font-semibold uppercase tracking-wider shrink-0 mr-1">
            Presets:
          </span>
          {PRESET_TEMPLATES.map((tmpl, idx) => {
            const Icon = tmpl.icon;
            return (
              <button
                key={idx}
                type="button"
                onClick={() => setInputPrompt(tmpl.prompt)}
                disabled={isLoading}
                className="inline-flex items-center gap-1 px-2 py-0.5 rounded-md text-[11px] bg-elevated hover:bg-line text-ink-secondary hover:text-ink-primary border border-line whitespace-nowrap cursor-pointer transition-colors"
              >
                <Icon className="h-3 w-3 text-brand shrink-0" aria-hidden="true" />
                <span>{tmpl.label}</span>
              </button>
            );
          })}
        </div>

        {/* Textarea + Send button */}
        <div className="relative rounded-xl bg-elevated border border-line focus-within:border-brand transition-colors p-2">
          <textarea
            ref={textareaRef}
            value={inputPrompt}
            onChange={handleTextareaChange}
            onKeyDown={handleKeyDown}
            disabled={isLoading}
            rows={2}
            placeholder="Describe your cloud architecture requirement... (Enter to send, Shift+Enter for newline)"
            className="w-full bg-transparent text-xs text-ink-primary placeholder-ink-tertiary resize-none focus:outline-none leading-relaxed font-sans pr-14"
          />

          <div className="flex items-center justify-between pt-1 border-t border-line/60">
            <span className="text-[10px] font-mono text-ink-tertiary">
              {inputPrompt.length} chars
            </span>

            {isLoading ? (
              <Button
                key="chat-stop-btn"
                variant="destructive"
                size="sm"
                disabled={false}
                onClick={onCancelChat}
                leftIcon={<Square className="h-3 w-3 fill-current" />}
              >
                Stop
              </Button>
            ) : (
              <Button
                key="chat-send-btn"
                variant="primary"
                size="sm"
                disabled={!inputPrompt.trim()}
                onClick={handleSubmit}
                rightIcon={<Send className="h-3 w-3" />}
              >
                Send
              </Button>
            )}
          </div>
        </div>
      </div>
    </div>
  );
};
