import React from 'react';

export interface NavSectionProps {
  label: string;
  collapsed?: boolean;
  children: React.ReactNode;
}

export const NavSection: React.FC<NavSectionProps> = ({ label, collapsed = false, children }) => {
  return (
    <div className="space-y-1">
      {!collapsed ? (
        <div className="px-4 py-1.5 text-[11px] font-semibold uppercase tracking-wider text-nav-section select-none">
          {label.toUpperCase()}
        </div>
      ) : (
        <div className="mx-3 my-1 border-t border-line" aria-hidden="true" />
      )}
      <nav className="space-y-0.5" aria-label={`${label} Navigation`}>
        {children}
      </nav>
    </div>
  );
};

export default NavSection;
