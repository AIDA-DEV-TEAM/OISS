/**
 * The applied-context strip — DESIGN.md §4.
 *
 * Sits directly under the filter bar on every screen that shows figures:
 * sources, period, row count and data-origin mix. It is part of the layout, not
 * an afterthought, so a reviewer can always see what produced the numbers above.
 *
 * Takes either the backend's AppliedContext (query screens) or the explicit
 * fields the ingest and lineage screens have to hand.
 */
import type { ReactNode } from 'react';

import type { AppliedContext, SourceDataset } from '@/api/client';
import { Figure, cn } from '@/components/primitives';

function Item({ label, children }: { label: string; children: ReactNode }) {
  return (
    <div className="flex min-w-0 flex-col gap-0.5">
      <span className="text-caption font-medium uppercase tracking-header text-ink-subtle">
        {label}
      </span>
      <span className="truncate text-body text-ink">{children}</span>
    </div>
  );
}

export interface ContextStripProps {
  sources: Array<Pick<SourceDataset, 'dataset_name' | 'dataset_version_id'>>;
  period?: string;
  rowCount?: number;
  underlyingRowCount?: number;
  origin?: { official: number; synthetic: number };
  extra?: ReactNode;
  className?: string;
}

export function AppliedContextStrip({
  sources,
  period,
  rowCount,
  underlyingRowCount,
  origin,
  extra,
  className,
}: ContextStripProps) {
  const number = (value: number) => value.toLocaleString('en-IN');
  return (
    <div
      className={cn(
        'flex flex-wrap items-start gap-x-8 gap-y-3 rounded border border-line bg-surface-alt px-card py-2.5',
        className,
      )}
      aria-label="Applied context"
    >
      {/* Every figure above comes from these versions, and only these: a query
          counts one active version per dataset. Naming them is what makes the
          number on screen traceable to a file. */}
      <Item label="Active dataset versions">
        {sources.length === 0 ? (
          <span className="text-ink-muted">None</span>
        ) : sources.length === 1 ? (
          <span title={sources[0].dataset_version_id}>{sources[0].dataset_name}</span>
        ) : (
          <span
            title={sources.map((source) => source.dataset_version_id).join(', ')}
          >
            <Figure>{sources.length}</Figure> versions ·{' '}
            {sources.map((source) => source.dataset_name).join(', ')}
          </span>
        )}
      </Item>

      {period && <Item label="Period">{period}</Item>}

      {rowCount !== undefined && (
        <Item label="Rows shown">
          <Figure>{number(rowCount)}</Figure>
          {underlyingRowCount !== undefined && underlyingRowCount !== rowCount && (
            <span className="text-ink-muted">
              {' '}
              of <Figure>{number(underlyingRowCount)}</Figure>
            </span>
          )}
        </Item>
      )}

      {origin && (
        <Item label="Data origin">
          <span className="inline-flex items-center gap-2">
            <span>
              <Figure>{number(origin.official)}</Figure> official
            </span>
            {origin.synthetic > 0 && (
              <>
                <span className="text-ink-subtle" aria-hidden="true">
                  ·
                </span>
                <span className="inline-flex items-center gap-1.5">
                  <Figure>{number(origin.synthetic)}</Figure> modelled
                </span>
              </>
            )}
          </span>
        </Item>
      )}

      {extra}
    </div>
  );
}

/** Convenience wrapper for screens that already hold a backend AppliedContext. */
export function QueryContextStrip({ context }: { context: AppliedContext }) {
  return (
    <AppliedContextStrip
      sources={context.source_datasets}
      period={
        context.period
          ? `${String(context.period.from ?? '…')} to ${String(context.period.to ?? '…')}`
          : undefined
      }
      rowCount={context.row_count}
      underlyingRowCount={context.underlying_row_count}
      origin={{
        official: context.data_origin.official ?? 0,
        synthetic: context.data_origin.synthetic ?? 0,
      }}
    />
  );
}
