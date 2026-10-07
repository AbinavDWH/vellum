import React, { useState, useEffect } from 'react';
import { FolderKanban, Search, RefreshCw, ArrowUpRight, DollarSign, Calendar, Layers } from 'lucide-react';
import { PlanSummary } from '../../types';
import { api } from '../../services/api';
import { Chip } from '../ui/Chip';
import { Button } from '../ui/Button';
import { EmptyState } from '../ui/EmptyState';
import { Skeleton } from '../ui/Skeleton';
import { formatCurrency, formatRelativeTime } from '../../lib/utils';

export interface PlansViewProps {
  onSelectPlan: (planId: string) => void;
  onGoToDesigner: () => void;
}

export const PlansView: React.FC<PlansViewProps> = ({ onSelectPlan, onGoToDesigner }) => {
  const [plans, setPlans] = useState<PlanSummary[]>([]);
  const [loading, setLoading] = useState(true);
  const [query, setQuery] = useState('');
  const [riskFilter, setRiskFilter] = useState<string>('all');

  const fetchPlans = async () => {
    setLoading(true);
    try {
      const data = await api.getPlans(50);
      setPlans(data);
    } catch (err) {
      console.error('Failed to fetch plans', err);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    fetchPlans();
  }, []);

  const filteredPlans = plans.filter((p) => {
    const matchesQuery =
      !query.trim() ||
      p.plan_id.toLowerCase().includes(query.toLowerCase()) ||
      p.intent.toLowerCase().includes(query.toLowerCase()) ||
      (p.prompt && p.prompt.toLowerCase().includes(query.toLowerCase()));

    const matchesRisk = riskFilter === 'all' || p.risk_level.toLowerCase() === riskFilter.toLowerCase();
    return matchesQuery && matchesRisk;
  });

  return (
    <div className="space-y-6">
      {/* View Header */}
      <div className="flex flex-wrap items-center justify-between gap-4">
        <div>
          <h1 className="text-xl font-bold tracking-tight text-ink-primary">Infrastructure Plans</h1>
          <p className="text-xs text-ink-secondary">
            Generated cloud architectures and database schema plans stored in Vellum
          </p>
        </div>
        <div className="flex items-center gap-2">
          <Button
            variant="secondary"
            size="sm"
            onClick={fetchPlans}
            disabled={loading}
            leftIcon={<RefreshCw className={`h-3.5 w-3.5 ${loading ? 'animate-spin' : ''}`} />}
          >
            Refresh
          </Button>
          <Button variant="primary" size="sm" onClick={onGoToDesigner}>
            New Architecture
          </Button>
        </div>
      </div>

      {/* Filter Toolbar */}
      <div className="flex flex-wrap items-center justify-between gap-3 p-3 rounded-xl bg-surface border border-line">
        <div className="flex items-center gap-2 flex-1 max-w-md">
          <Search className="h-4 w-4 text-ink-tertiary" aria-hidden="true" />
          <input
            type="text"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            placeholder="Search plans by ID, intent, or keywords..."
            className="w-full bg-transparent text-xs text-ink-primary placeholder-ink-tertiary focus:outline-none"
          />
        </div>

        {/* Risk Filter Chips */}
        <div className="flex items-center gap-1.5">
          <span className="text-xs text-ink-tertiary mr-1">Risk:</span>
          {['all', 'low', 'medium', 'high', 'critical'].map((r) => (
            <button
              key={r}
              onClick={() => setRiskFilter(r)}
              className={`px-2 py-0.5 rounded-full text-xs font-medium uppercase transition-colors cursor-pointer ${
                riskFilter === r
                  ? 'bg-brand/20 text-brand border border-brand/40'
                  : 'bg-elevated text-ink-secondary hover:text-ink-primary border border-line'
              }`}
            >
              {r}
            </button>
          ))}
        </div>
      </div>

      {/* Plans List / Table */}
      {loading ? (
        <div className="space-y-3">
          {[...Array(4)].map((_, i) => (
            <Skeleton key={i} className="h-20 w-full" />
          ))}
        </div>
      ) : filteredPlans.length === 0 ? (
        <EmptyState
          icon={<FolderKanban className="h-6 w-6 text-brand" />}
          title="No infrastructure plans found"
          hint={
            query || riskFilter !== 'all'
              ? 'No plans match your search and filter criteria.'
              : 'You have not generated any infrastructure plans yet. Describe an architecture in the Designer to begin.'
          }
          actionLabel="Open Designer"
          onAction={onGoToDesigner}
        />
      ) : (
        <div className="grid grid-cols-1 gap-3">
          {filteredPlans.map((plan) => (
            <div
              key={plan.plan_id}
              onClick={() => onSelectPlan(plan.plan_id)}
              className="p-4 rounded-xl bg-surface border border-line hover:border-brand/40 hover:bg-elevated transition-all cursor-pointer group flex flex-col md:flex-row md:items-center justify-between gap-4"
            >
              <div className="space-y-1.5 flex-1 min-w-0">
                <div className="flex items-center gap-2.5 flex-wrap">
                  <span className="font-mono text-xs font-semibold text-brand group-hover:underline">
                    {plan.plan_id}
                  </span>
                  <Chip risk={plan.risk_level} showRiskIcon />
                  <span className="text-[10px] uppercase font-mono px-2 py-0.5 rounded bg-elevated border border-line text-ink-secondary">
                    Status: {plan.status}
                  </span>
                </div>
                <h3 className="text-sm font-semibold text-ink-primary truncate">
                  {plan.prompt || plan.intent}
                </h3>
                <div className="flex items-center gap-4 text-xs text-ink-secondary flex-wrap">
                  <div className="flex items-center gap-1">
                    <Layers className="h-3.5 w-3.5 text-ink-tertiary" />
                    <span>Intent: {plan.intent.replace(/_/g, ' ')}</span>
                  </div>
                  {plan.created_at && (
                    <div className="flex items-center gap-1">
                      <Calendar className="h-3.5 w-3.5 text-ink-tertiary" />
                      <span>{formatRelativeTime(plan.created_at)}</span>
                    </div>
                  )}
                </div>
              </div>

              {/* Cost & Action */}
              <div className="flex items-center gap-4 shrink-0 justify-between md:justify-end">
                <div className="text-right">
                  <div className="text-[11px] text-ink-tertiary">Est. Cloud Cost</div>
                  <div className="text-sm font-bold text-ok font-mono">
                    {formatCurrency(plan.estimated_cost_monthly || 0)}/mo
                  </div>
                </div>
                <div className="h-8 w-8 rounded-lg bg-elevated group-hover:bg-brand/10 border border-line group-hover:border-brand/30 flex items-center justify-center text-ink-secondary group-hover:text-brand transition-colors">
                  <ArrowUpRight className="h-4 w-4" />
                </div>
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  );
};
