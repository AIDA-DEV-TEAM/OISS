import type { ReactNode } from 'react';

/** Page title with an optional sticky filter bar beneath it (DESIGN.md §4). */
export function PageHeader({
  title,
  description,
  actions,
  filterBar,
}: {
  title: string;
  description?: ReactNode;
  actions?: ReactNode;
  filterBar?: ReactNode;
}) {
  return (
    <div className="mb-4">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <h1 className="text-page font-semibold text-ink">{title}</h1>
          {description && (
            <p className="mt-1 max-w-3xl text-body text-ink-muted">{description}</p>
          )}
        </div>
        {actions && <div className="flex items-center gap-2">{actions}</div>}
      </div>
      {filterBar && (
        <div className="sticky top-0 z-20 -mx-gutter mt-3 border-b border-line bg-surface-alt/95 px-gutter py-3 backdrop-blur">
          {filterBar}
        </div>
      )}
    </div>
  );
}
