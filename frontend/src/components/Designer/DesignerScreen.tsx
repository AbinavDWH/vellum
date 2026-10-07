import React from 'react';
import { ChatPane, ChatMessage } from './ChatPane';
import { WorkspacePane } from './WorkspacePane';
import { PlanResponse } from '../../types';

export interface DesignerScreenProps {
  messages: ChatMessage[];
  onSendMessage: (prompt: string) => void;
  isLoading: boolean;
  currentPlan: PlanResponse | null;
  onApprovePlan: (confirmationText?: string, customTf?: string, customSql?: string) => void;
  onRejectPlan: () => void;
  onModifyPlan: (modifications: string) => void;
  onClearHistory?: () => void;
  onOpenHistory?: () => void;
  onNewChat?: () => void;
  sessionTitle?: string;
  onReexecutePlan?: () => void;
  onViewExecution?: () => void;
  onViewAudit?: () => void;
  driftDiff?: {
    missing?: string[];
    verified?: number;
    expected?: string[];
    found?: string[];
  } | null;
  requirementsMd?: string;
  onUpdateRequirements?: (newMd: string) => void;
  onSynthesizePlan?: () => void;
  onCancelChat?: () => void;
}

export const DesignerScreen: React.FC<DesignerScreenProps> = ({
  messages,
  onSendMessage,
  isLoading,
  currentPlan,
  onApprovePlan,
  onRejectPlan,
  onModifyPlan,
  onClearHistory,
  onOpenHistory,
  onNewChat,
  sessionTitle,
  onReexecutePlan,
  onViewExecution,
  onViewAudit,
  driftDiff,
  requirementsMd,
  onUpdateRequirements,
  onSynthesizePlan,
  onCancelChat,
}) => {
  return (
    <div className="h-[calc(100vh-8.5rem)] flex flex-col lg:flex-row overflow-hidden rounded-xl border border-line bg-surface shadow-sm">
      {/* Left Chat Pane (40%, min 360px) */}
      <div className="w-full lg:w-[40%] lg:min-w-[360px] h-1/2 lg:h-full shrink-0">
        <ChatPane
          messages={messages}
          onSendMessage={onSendMessage}
          isLoading={isLoading}
          onCancelChat={onCancelChat}
          onClearHistory={onClearHistory}
          onOpenHistory={onOpenHistory}
          onNewChat={onNewChat}
          sessionTitle={sessionTitle}
          onSynthesizePlan={onSynthesizePlan}
          requirementsMd={requirementsMd}
        />
      </div>

      {/* Right Workspace Pane (60%) */}
      <div className="w-full lg:w-[60%] h-1/2 lg:h-full flex-1 min-w-0">
        <WorkspacePane
          plan={currentPlan}
          onApprove={onApprovePlan}
          onReject={onRejectPlan}
          onModify={onModifyPlan}
          isProcessing={isLoading}
          onReexecute={onReexecutePlan}
          onViewExecution={onViewExecution}
          onViewAudit={onViewAudit}
          driftDiff={driftDiff}
          requirementsMd={requirementsMd}
          onUpdateRequirements={onUpdateRequirements}
          onSynthesizePlan={onSynthesizePlan}
        />
      </div>
    </div>
  );
};
