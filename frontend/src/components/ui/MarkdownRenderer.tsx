import React, { useState } from 'react';
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import { CopyButton } from './CopyButton';
import { Code, Eye } from 'lucide-react';
import { cn } from '../../lib/utils';

export interface MarkdownRendererProps {
  content: string;
  className?: string;
  showRawToggle?: boolean;
  defaultRaw?: boolean;
}

export const MarkdownRenderer: React.FC<MarkdownRendererProps> = ({
  content,
  className,
  showRawToggle = false,
  defaultRaw = false,
}) => {
  const [isRaw, setIsRaw] = useState(defaultRaw);

  if (!content) return null;

  return (
    <div className={cn('relative group/md text-xs leading-relaxed', className)}>
      {showRawToggle && (
        <div className="flex items-center justify-end gap-1.5 mb-2 pb-1 border-b border-line/40">
          <button
            type="button"
            onClick={() => setIsRaw(!isRaw)}
            className="flex items-center gap-1 text-[10px] px-1.5 py-0.5 rounded bg-base border border-line text-ink-secondary hover:text-ink-primary transition-colors cursor-pointer"
            title={isRaw ? 'Switch to formatted view' : 'Switch to raw markdown'}
          >
            {isRaw ? (
              <>
                <Eye className="h-2.5 w-2.5 text-brand" />
                <span>Formatted</span>
              </>
            ) : (
              <>
                <Code className="h-2.5 w-2.5 text-ink-tertiary" />
                <span>Raw</span>
              </>
            )}
          </button>
          <CopyButton value={content} label="Copy" className="text-[10px]" />
        </div>
      )}

      {isRaw ? (
        <pre className="p-3 bg-base/80 border border-line rounded-lg font-mono text-[11px] leading-relaxed whitespace-pre-wrap select-text text-ink-secondary overflow-x-auto">
          {content}
        </pre>
      ) : (
        <div className="markdown-content space-y-2 text-ink-primary">
          <ReactMarkdown
            remarkPlugins={[remarkGfm]}
            components={{
              p: ({ children }) => (
                <p className="mb-2 last:mb-0 leading-relaxed text-ink-primary">{children}</p>
              ),
              strong: ({ children }) => (
                <strong className="font-semibold text-ink-primary">{children}</strong>
              ),
              em: ({ children }) => (
                <em className="italic text-ink-primary">{children}</em>
              ),
              h1: ({ children }) => (
                <h1 className="text-sm font-bold text-ink-primary mt-3 mb-1.5 border-b border-line/60 pb-1 flex items-center gap-1.5">
                  {children}
                </h1>
              ),
              h2: ({ children }) => (
                <h2 className="text-xs font-bold text-ink-primary mt-2.5 mb-1.5 text-brand flex items-center gap-1.5">
                  {children}
                </h2>
              ),
              h3: ({ children }) => (
                <h3 className="text-xs font-semibold text-ink-primary mt-2 mb-1">
                  {children}
                </h3>
              ),
              h4: ({ children }) => (
                <h4 className="text-[11px] font-semibold text-ink-secondary mt-1.5 mb-0.5">
                  {children}
                </h4>
              ),
              ul: ({ children }) => (
                <ul className="list-disc list-outside pl-4 space-y-1 my-1.5 text-ink-primary">
                  {children}
                </ul>
              ),
              ol: ({ children }) => (
                <ol className="list-decimal list-outside pl-4 space-y-1 my-1.5 text-ink-primary">
                  {children}
                </ol>
              ),
              li: ({ children }) => (
                <li className="leading-relaxed pl-0.5">{children}</li>
              ),
              blockquote: ({ children }) => (
                <blockquote className="border-l-2 border-brand/60 pl-3 my-2 italic text-ink-secondary bg-surface/50 py-1 rounded-r">
                  {children}
                </blockquote>
              ),
              hr: () => <hr className="my-2.5 border-line" />,
              a: ({ href, children }) => (
                <a
                  href={href}
                  target="_blank"
                  rel="noopener noreferrer"
                  className="text-brand hover:underline font-medium inline-flex items-center gap-0.5"
                >
                  {children}
                </a>
              ),
              table: ({ children }) => (
                <div className="overflow-x-auto my-2.5 rounded-lg border border-line shadow-xs">
                  <table className="w-full text-[11px] border-collapse text-left">
                    {children}
                  </table>
                </div>
              ),
              thead: ({ children }) => (
                <thead className="bg-elevated border-b border-line text-ink-primary font-semibold">
                  {children}
                </thead>
              ),
              tbody: ({ children }) => (
                <tbody className="divide-y divide-line/60 bg-base/40">
                  {children}
                </tbody>
              ),
              tr: ({ children }) => (
                <tr className="hover:bg-elevated/40 transition-colors">
                  {children}
                </tr>
              ),
              th: ({ children }) => (
                <th className="px-3 py-1.5 text-ink-primary font-semibold text-[11px]">
                  {children}
                </th>
              ),
              td: ({ children }) => (
                <td className="px-3 py-1.5 text-ink-secondary text-[11px] align-top">
                  {children}
                </td>
              ),
              code: ({ className: codeClassName, children, ...props }) => {
                const match = /language-(\w+)/.exec(codeClassName || '');
                const isInline = !codeClassName && !String(children).includes('\n');

                if (isInline) {
                  return (
                    <code
                      className="px-1.5 py-0.5 rounded bg-base border border-line text-[11px] font-mono text-brand font-medium"
                      {...props}
                    >
                      {children}
                    </code>
                  );
                }

                const codeString = String(children).replace(/\n$/, '');
                return (
                  <div className="relative group/code my-2 rounded-lg border border-line overflow-hidden bg-base">
                    <div className="flex items-center justify-between px-3 py-1 bg-elevated/70 border-b border-line text-[10px] text-ink-secondary">
                      <span className="font-mono">{match ? match[1] : 'code'}</span>
                      <CopyButton value={codeString} label="Copy" className="text-[10px]" />
                    </div>
                    <pre className="p-3 font-mono text-[11px] text-ink-primary overflow-x-auto leading-relaxed">
                      <code>{children}</code>
                    </pre>
                  </div>
                );
              },
            }}
          >
            {content}
          </ReactMarkdown>
        </div>
      )}
    </div>
  );
};
