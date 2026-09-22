/**
 * The four storage layers for one dataset, with row counts and what happened
 * between them.
 *
 * The transition text comes from the backend, which derives it from the counts
 * rather than from a per-dataset description, so it cannot drift from what the
 * loader actually did.
 */
import type { LayerStage } from '@/api/client';
import { Card, Figure, cn } from '@/components/primitives';
import { formatCount } from '@/lib/format';

const LAYER_TONE: Record<string, string> = {
  raw: 'border-l-aggregated',
  quarantine: 'border-l-error',
  staging: 'border-l-info',
  analytics: 'border-l-success',
};

export function LayerFlow({ stages }: { stages: LayerStage[] }) {
  return (
    <Card
      title="Storage layers"
      description="Raw / landing → validation / quarantine → cleansed / staging → analytics-ready."
      bodyClassName="p-card"
    >
      <ol className="grid grid-cols-1 gap-3 lg:grid-cols-4">
        {stages.map((stage, index) => (
          <li
            key={stage.layer}
            className={cn(
              'relative rounded border border-line border-l-rule bg-surface p-3',
              LAYER_TONE[stage.layer] ?? 'border-l-line-strong',
            )}
          >
            <p className="text-caption font-medium uppercase tracking-header text-ink-subtle">
              {index + 1}. {stage.label}
            </p>
            <p className="mt-1">
              <Figure className="text-kpi font-semibold text-ink">
                {formatCount(stage.row_count)}
              </Figure>{' '}
              <span className="text-caption text-ink-muted">rows</span>
            </p>
            {stage.table && (
              <p className="mt-0.5 truncate text-caption text-ink-subtle" title={stage.table}>
                <code>{stage.table}</code>
              </p>
            )}
            <p className="mt-2 text-caption text-ink-muted">{stage.transition}</p>
            <p className="mt-2 border-t border-line pt-2 text-caption text-ink-subtle">
              {stage.purpose}
            </p>
          </li>
        ))}
      </ol>
    </Card>
  );
}
