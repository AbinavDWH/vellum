import React, { forwardRef } from 'react';
import { Loader2 } from 'lucide-react';
import { cn } from '../../lib/utils';

export interface ButtonProps extends React.ButtonHTMLAttributes<HTMLButtonElement> {
  variant?: 'primary' | 'secondary' | 'ghost' | 'destructive' | 'outline';
  size?: 'sm' | 'md' | 'lg' | 'icon';
  loading?: boolean;
  leftIcon?: React.ReactNode;
  rightIcon?: React.ReactNode;
}

export const Button = forwardRef<HTMLButtonElement, ButtonProps>(
  (
    {
      className,
      variant = 'secondary',
      size = 'md',
      loading = false,
      disabled,
      children,
      leftIcon,
      rightIcon,
      ...props
    },
    ref
  ) => {
    const baseStyles =
      'inline-flex items-center justify-center font-medium transition-colors rounded-lg select-none focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand focus-visible:ring-offset-2 focus-visible:ring-offset-base disabled:pointer-events-none disabled:opacity-50 cursor-pointer disabled:cursor-not-allowed';

    const variants = {
      primary:
        'bg-brand text-brand-ink font-semibold hover:bg-brand-hover active:opacity-90 shadow-sm transition-colors',
      secondary:
        'bg-elevated hover:bg-surface text-ink-primary border border-line active:bg-base',
      ghost:
        'bg-transparent hover:bg-elevated text-ink-secondary hover:text-ink-primary active:bg-surface',
      destructive:
        'bg-crit/15 hover:bg-crit/25 text-crit border border-crit/30 active:bg-crit/30',
      outline:
        'bg-transparent border border-line hover:border-brand/40 hover:bg-elevated text-ink-primary active:bg-surface',
    };

    const sizes = {
      sm: 'h-8 px-3 text-xs gap-1.5 min-w-[32px]',
      md: 'h-9 px-4 text-sm gap-2 min-w-[36px]',
      lg: 'h-11 px-6 text-base gap-2.5 min-w-[44px]',
      icon: 'h-9 w-9 p-0',
    };

    return (
      <button
        ref={ref}
        disabled={disabled || loading}
        className={cn(baseStyles, variants[variant], sizes[size], className)}
        {...props}
      >
        {loading ? (
          <Loader2 className="h-4 w-4 animate-spin text-current shrink-0" aria-hidden="true" />
        ) : (
          leftIcon && <span className="shrink-0" aria-hidden="true">{leftIcon}</span>
        )}
        {children && <span>{children}</span>}
        {!loading && rightIcon && <span className="shrink-0" aria-hidden="true">{rightIcon}</span>}
      </button>
    );
  }
);

Button.displayName = 'Button';
