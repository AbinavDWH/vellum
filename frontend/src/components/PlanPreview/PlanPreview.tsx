import React from 'react';
import { PlanResponse } from '../../types';
import { WorkspacePane } from '../Designer/WorkspacePane';

export interface PlanPreviewProps {
  plan: PlanResponse;
  onApprove: (confirmationText?: string, customTf?: string, customSql?: string) => void;
  onReject: () => void;
  onModify: (modifications: string) => void;
  isProcessing: boolean;
}

export const PlanPreview: React.FC<PlanPreviewProps> = ({
  plan,
  onApprove,
  onReject,
  onModify,
  isProcessing,
}) => {
  return (
    <div className="rounded-xl border border-line bg-surface overflow-hidden shadow-sm">
      <WorkspacePane
        plan={plan}
        onApprove={onApprove}
        onReject={onReject}
        onModify={onModify}
        isProcessing={isProcessing}
      />
    </div>
  );
};
