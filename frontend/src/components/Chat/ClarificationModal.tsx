import React, { useState } from 'react';
import { HelpCircle, ArrowRight } from 'lucide-react';
import { ClarificationResponse } from '../../types';
import { Modal } from '../ui/Modal';
import { Button } from '../ui/Button';

export interface ClarificationModalProps {
  clarification: ClarificationResponse;
  originalPrompt: string;
  onSubmitAnswers: (combinedPrompt: string) => void;
  onCancel: () => void;
}

export const ClarificationModal: React.FC<ClarificationModalProps> = ({
  clarification,
  originalPrompt,
  onSubmitAnswers,
  onCancel,
}) => {
  const [answers, setAnswers] = useState<Record<number, string>>(() => {
    const initial: Record<number, string> = {};
    clarification.questions.forEach((q, idx) => {
      if (q.default_suggestion) {
        initial[idx] = q.default_suggestion;
      }
    });
    return initial;
  });

  const handleApply = () => {
    let combined = originalPrompt.trim();
    clarification.questions.forEach((q, idx) => {
      const ans = answers[idx];
      if (ans && ans.trim()) {
        combined += `\n[Clarification]: ${q.question} -> ${ans.trim()}`;
      }
    });
    onSubmitAnswers(combined);
  };

  return (
    <Modal
      isOpen={true}
      onClose={onCancel}
      title="Clarification Needed"
      description="To build an optimal infrastructure design, answer or accept the suggested details below:"
      icon={<HelpCircle className="h-5 w-5 text-brand" />}
      footer={
        <>
          <Button variant="secondary" size="sm" onClick={onCancel}>
            Cancel
          </Button>
          <Button variant="primary" size="sm" onClick={handleApply} rightIcon={<ArrowRight className="h-3.5 w-3.5" />}>
            Proceed with Answers
          </Button>
        </>
      }
    >
      <div className="space-y-3">
        {clarification.questions.map((q, idx) => (
          <div key={idx} className="p-3 bg-base rounded-xl border border-line space-y-2">
            <label className="block text-xs font-semibold text-ink-primary">{q.question}</label>
            {q.context && <p className="text-[11px] text-ink-secondary">{q.context}</p>}
            
            {q.options && q.options.length > 0 ? (
              <div className="space-y-1.5 pt-1">
                <div className="flex flex-wrap gap-2">
                  {q.options.map((opt, oIdx) => {
                    const isSelected = (answers[idx] || q.default_suggestion) === opt;
                    return (
                      <button
                        key={oIdx}
                        type="button"
                        onClick={() => setAnswers({ ...answers, [idx]: opt })}
                        className={`px-3 py-1.5 rounded-lg text-xs font-medium border transition-all ${
                          isSelected
                            ? 'bg-brand/20 border-brand text-brand ring-1 ring-brand'
                            : 'bg-elevated border-line text-ink-secondary hover:border-line/80 hover:text-ink-primary'
                        }`}
                      >
                        {opt}
                      </button>
                    );
                  })}
                </div>
              </div>
            ) : (
              <input
                type="text"
                value={answers[idx] || ''}
                onChange={(e) => setAnswers({ ...answers, [idx]: e.target.value })}
                placeholder={q.default_suggestion || 'Type your answer...'}
                className="w-full bg-elevated border border-line rounded-lg px-3 py-1.5 text-xs text-ink-primary focus:outline-none focus:ring-1 focus:ring-brand font-sans"
              />
            )}
          </div>
        ))}
      </div>
    </Modal>
  );
};
