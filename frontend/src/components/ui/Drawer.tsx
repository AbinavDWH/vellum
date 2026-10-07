import React, { useEffect, useRef } from 'react';
import { X } from 'lucide-react';
import { cn } from '../../lib/utils';

export interface DrawerProps {
  isOpen: boolean;
  onClose: () => void;
  title: React.ReactNode;
  description?: React.ReactNode;
  children: React.ReactNode;
  footer?: React.ReactNode;
  width?: string; // defaults to 480px
}

export const Drawer: React.FC<DrawerProps> = ({
  isOpen,
  onClose,
  title,
  description,
  children,
  footer,
  width = 'w-full sm:w-[480px]',
}) => {
  const drawerRef = useRef<HTMLDivElement>(null);

  // Close on Escape & trap focus
  useEffect(() => {
    const handleKeyDown = (e: KeyboardEvent) => {
      if (e.key === 'Escape' && isOpen) {
        onClose();
      }
    };

    if (isOpen) {
      document.body.style.overflow = 'hidden';
      window.addEventListener('keydown', handleKeyDown);
    } else {
      document.body.style.overflow = '';
    }

    return () => {
      document.body.style.overflow = '';
      window.removeEventListener('keydown', handleKeyDown);
    };
  }, [isOpen, onClose]);

  if (!isOpen) return null;

  return (
    <div
      className="fixed inset-0 z-50 flex justify-end bg-base/80 backdrop-blur-sm transition-opacity duration-200"
      onClick={onClose}
      aria-modal="true"
      role="dialog"
    >
      <div
        ref={drawerRef}
        className={cn(
          'relative flex flex-col h-full bg-elevated border-l border-line shadow-drawer z-10 transition-transform duration-200 ease-out',
          width
        )}
        onClick={(e) => e.stopPropagation()}
      >
        {/* Drawer Header */}
        <div className="flex items-start justify-between p-6 border-b border-line shrink-0">
          <div className="space-y-1 pr-4">
            <h2 className="text-base font-semibold text-ink-primary">{title}</h2>
            {description && <p className="text-xs text-ink-secondary">{description}</p>}
          </div>
          <button
            onClick={onClose}
            aria-label="Close drawer"
            className="p-1.5 rounded-lg text-ink-secondary hover:text-ink-primary hover:bg-surface focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand transition-colors"
          >
            <X className="h-4 w-4" aria-hidden="true" />
          </button>
        </div>

        {/* Drawer Content */}
        <div className="flex-1 overflow-y-auto p-6 space-y-6">
          {children}
        </div>

        {/* Drawer Footer */}
        {footer && (
          <div className="p-4 border-t border-line bg-surface shrink-0">
            {footer}
          </div>
        )}
      </div>
    </div>
  );
};
