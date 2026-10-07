import React from 'react';
import { Topbar, TopbarProps } from './Shell/Topbar';

// Preserved for component responsibility compatibility
export const Navbar: React.FC<any> = (props) => {
  return (
    <Topbar
      onToggleSidebar={props.onToggleSidebar || (() => {})}
      onOpenCommandPalette={props.onOpenCommandPalette || (() => {})}
      sidebarCollapsed={props.sidebarCollapsed || false}
      wsConnected={props.wsConnected || false}
    />
  );
};
