import React, { createContext, useContext, useState, useCallback } from 'react';
import { CheckCircle2, AlertTriangle, AlertCircle, Info, X } from 'lucide-react';
import { cn } from '../../lib/utils';

export type ToastType = 'success' | 'warn' | 'crit' | 'info';

export interface ToastMessage {
  id: string;
  title: string;
  description?: string;
  type?: ToastType;
}

interface ToastContextType {
  toast: (message: Omit<ToastMessage, 'id'>) => void;
}

const ToastContext = createContext<ToastContextType | undefined>(undefined);

export const ToastProvider: React.FC<{ children: React.ReactNode }> = ({ children }) => {
  const [toasts, setToasts] = useState<ToastMessage[]>([]);

  const toast = useCallback((msg: Omit<ToastMessage, 'id'>) => {
    const id = Math.random().toString(36).substring(2, 9);
    const newToast: ToastMessage = { ...msg, id };
    setToasts((prev) => [...prev, newToast]);

    setTimeout(() => {
      setToasts((prev) => prev.filter((t) => t.id !== id));
    }, 4000);
  }, []);

  const removeToast = (id: string) => {
    setToasts((prev) => prev.filter((t) => t.id !== id));
  };

  return (
    <ToastContext.Provider value={{ toast }}>
      {children}
      <div
        aria-live="polite"
        className="fixed bottom-4 right-4 z-50 flex flex-col gap-2 max-w-sm w-full pointer-events-none"
      >
        {toasts.map((t) => {
          const type = t.type || 'info';
          return (
            <div
              key={t.id}
              role={type === 'crit' ? 'alert' : 'status'}
              className={cn(
                'pointer-events-auto flex items-start gap-3 p-4 rounded-xl border bg-elevated shadow-modal transition-all duration-200',
                type === 'success' && 'border-ok/30 text-ink-primary',
                type === 'warn' && 'border-warn/30 text-ink-primary',
                type === 'crit' && 'border-crit/30 text-ink-primary',
                type === 'info' && 'border-brand/30 text-ink-primary'
              )}
            >
              <div className="shrink-0 mt-0.5">
                {type === 'success' && <CheckCircle2 className="h-4 w-4 text-ok" aria-hidden="true" />}
                {type === 'warn' && <AlertTriangle className="h-4 w-4 text-warn" aria-hidden="true" />}
                {type === 'crit' && <AlertCircle className="h-4 w-4 text-crit" aria-hidden="true" />}
                {type === 'info' && <Info className="h-4 w-4 text-brand" aria-hidden="true" />}
              </div>
              <div className="flex-1 space-y-0.5">
                <p className="text-xs font-semibold text-ink-primary">{t.title}</p>
                {t.description && <p className="text-[11px] text-ink-secondary">{t.description}</p>}
              </div>
              <button
                onClick={() => removeToast(t.id)}
                aria-label="Dismiss notification"
                className="shrink-0 p-1 text-ink-secondary hover:text-ink-primary rounded transition-colors"
              >
                <X className="h-3.5 w-3.5" aria-hidden="true" />
              </button>
            </div>
          );
        })}
      </div>
    </ToastContext.Provider>
  );
};

export const useToast = () => {
  const context = useContext(ToastContext);
  if (!context) {
    throw new Error('useToast must be used within a ToastProvider');
  }
  return context;
};
