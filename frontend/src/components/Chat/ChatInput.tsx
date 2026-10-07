import React, { useState } from 'react';
import { Send, Sparkles, Database, Cloud, Loader2 } from 'lucide-react';
import { Button } from '../ui/Button';

export interface ChatInputProps {
  onSubmit: (prompt: string) => void;
  isLoading: boolean;
}

const TEMPLATES = [
  {
    label: 'PostgreSQL + AWS S3',
    prompt:
      'I need a student management database with PostgreSQL. Students have name, email, enrollment date. They belong to departments. Deploy to AWS with a private database and S3 for student documents.',
    icon: Database,
  },
  {
    label: 'S3 App Assets Bucket',
    prompt: 'Create an S3 bucket called vellum-app-assets on AWS with versioning enabled.',
    icon: Cloud,
  },
  {
    label: 'Production VPC & Subnets',
    prompt:
      'Design an AWS VPC with CIDR 10.0.0.0/16, one public subnet in us-east-1a, and a private subnet for managed database.',
    icon: Sparkles,
  },
];

export const ChatInput: React.FC<ChatInputProps> = ({ onSubmit, isLoading }) => {
  const [prompt, setPrompt] = useState('');

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    if (!prompt.trim() || isLoading) return;
    onSubmit(prompt);
  };

  const handleKeyDown = (e: React.KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      handleSubmit(e);
    }
  };

  return (
    <div className="bg-surface border border-line rounded-xl p-4 shadow-sm">
      <div className="flex items-center justify-between mb-2">
        <div className="flex items-center gap-2 text-xs font-semibold uppercase tracking-wider text-ink-secondary">
          <Sparkles className="h-4 w-4 text-brand" />
          <span>Describe Your Infrastructure Requirement</span>
        </div>
        <span className="text-xs text-ink-tertiary font-mono">LM Studio Engine</span>
      </div>

      <form onSubmit={handleSubmit} className="space-y-3">
        <textarea
          value={prompt}
          onChange={(e) => setPrompt(e.target.value)}
          onKeyDown={handleKeyDown}
          placeholder="e.g. I need a PostgreSQL database for an e-commerce platform with users and orders tables, deployed on AWS with an S3 bucket for invoices..."
          rows={3}
          disabled={isLoading}
          className="w-full bg-elevated border border-line rounded-lg px-3.5 py-2.5 text-xs text-ink-primary placeholder-ink-tertiary focus:outline-none focus:ring-2 focus:ring-brand transition-colors resize-none font-sans"
        />

        <div className="flex flex-wrap items-center justify-between gap-2 pt-2 border-t border-line">
          <div className="flex flex-wrap gap-1.5 items-center">
            <span className="text-[11px] text-ink-tertiary mr-1 hidden sm:inline">Presets:</span>
            {TEMPLATES.map((tmpl, idx) => {
              const Icon = tmpl.icon;
              return (
                <button
                  key={idx}
                  type="button"
                  onClick={() => setPrompt(tmpl.prompt)}
                  disabled={isLoading}
                  className="inline-flex items-center gap-1.5 px-2 py-0.5 rounded-md text-[11px] bg-elevated hover:bg-surface text-ink-secondary hover:text-ink-primary border border-line transition-colors cursor-pointer"
                >
                  <Icon className="h-3 w-3 text-brand" />
                  <span>{tmpl.label}</span>
                </button>
              );
            })}
          </div>

          <Button
            type="submit"
            variant="primary"
            size="sm"
            disabled={!prompt.trim() || isLoading}
            loading={isLoading}
            rightIcon={<Send className="h-3.5 w-3.5" />}
          >
            {isLoading ? 'Designing Architecture...' : 'Generate Plan'}
          </Button>
        </div>
      </form>
    </div>
  );
};
