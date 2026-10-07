import React, { useState } from 'react';
import { cn } from '../../lib/utils';

export interface TooltipProps {
  content: React.ReactNode;
  children: React.ReactNode;
  side?: 'top' | 'bottom' | 'left' | 'right';
  align?: 'start' | 'center' | 'end';
  className?: string;
  wrapperClassName?: string;
}

export const Tooltip: React.FC<TooltipProps> = ({
  content,
  children,
  side = 'top',
  align = 'center',
  className,
  wrapperClassName,
}) => {
  const [visible, setVisible] = useState(false);

  const getPositionClass = () => {
    if (side === 'bottom') {
      const alignClass = align === 'end' ? 'right-0' : align === 'start' ? 'left-0' : 'left-1/2 -translate-x-1/2';
      return `top-full ${alignClass} mt-2`;
    }
    if (side === 'top') {
      const alignClass = align === 'end' ? 'right-0' : align === 'start' ? 'left-0' : 'left-1/2 -translate-x-1/2';
      return `bottom-full ${alignClass} mb-2`;
    }
    if (side === 'left') {
      return 'right-full top-1/2 -translate-y-1/2 mr-2';
    }
    return 'left-full top-1/2 -translate-y-1/2 ml-2';
  };

  return (
    <div
      className={cn("relative inline-flex", wrapperClassName)}
      onMouseEnter={() => setVisible(true)}
      onMouseLeave={() => setVisible(false)}
      onFocus={() => setVisible(true)}
      onBlur={() => setVisible(false)}
    >
      {children}
      {visible && content && (
        <div
          role="tooltip"
          className={cn(
            'absolute z-50 px-2.5 py-1 text-xs font-normal text-ink-primary bg-elevated border border-line rounded-md shadow-lg pointer-events-none whitespace-nowrap transition-opacity duration-150',
            getPositionClass(),
            className
          )}
        >
          {content}
        </div>
      )}
    </div>
  );
};
