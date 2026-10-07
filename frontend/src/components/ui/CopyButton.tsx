import React, { useState } from 'react';
import { Copy, Check } from 'lucide-react';
import { cn } from '../../lib/utils';

export interface CopyButtonProps {
  value: string;
  label?: string;
  showText?: boolean;
  className?: string;
  onCopy?: () => void;
}

export const CopyButton: React.FC<CopyButtonProps> = ({
  value,
  label = 'Copy',
  showText = false,
  className,
  onCopy,
}) => {
  const [copied, setCopied] = useState(false);

  const handleCopy = async (e: React.MouseEvent) => {
    e.stopPropagation();
    try {
      await navigator.clipboard.writeText(value);
      setCopied(true);
      onCopy?.();
      setTimeout(() => setCopied(false), 2000);
    } catch (err) {
      console.error('Failed to copy', err);
    }
  };

  return (
    <button
      type="button"
      onClick={handleCopy}
      aria-label={copied ? 'Copied to clipboard' : label}
      title={copied ? 'Copied!' : label}
      className={cn(
        'inline-flex items-center gap-1.5 p-1 rounded-md text-ink-secondary hover:text-ink-primary hover:bg-elevated transition-colors cursor-pointer focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand',
        showText && 'px-2.5 py-1 text-xs border border-line bg-surface',
        className
      )}
    >
      {copied ? (
        <Check className="h-3.5 w-3.5 text-ok shrink-0" aria-hidden="true" />
      ) : (
        <Copy className="h-3.5 w-3.5 shrink-0" aria-hidden="true" />
      )}
      {showText && <span>{copied ? 'Copied' : label}</span>}
    </button>
  );
};
