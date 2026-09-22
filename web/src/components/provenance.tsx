/**
 * CaveatList — DESIGN.md §5.
 *
 * The per-figure provenance badges that used to live here were replaced by the
 * panel-level ProvenanceNote (src/components/ProvenanceNote.tsx), whose wording
 * is derived in src/lib/provenance.ts from data_origin, annual_level_basis and
 * grain_source.
 */
import type { Caveat } from '@/api/client';
import { Figure, cn } from '@/components/primitives';

const CAVEAT_TONE: Record<string, 'error' | 'warning' | 'info'> = {
  error: 'error',
  warning: 'warning',
  info: 'info',
};

/**
 * DESIGN.md §5: renders the backend's `caveats` array verbatim, in plain
 * language, with affected-row counts. Every screen showing figures renders it,
 * so the narrative never has to invent its own hedges.
 */
export function CaveatList({
  caveats,
  className,
  emptyLabel,
}: {
  caveats: Caveat[];
  className?: string;
  emptyLabel?: string;
}) {
  if (caveats.length === 0) {
    return emptyLabel ? (
      <p className={cn('text-caption text-ink-subtle', className)}>{emptyLabel}</p>
    ) : null;
  }
  return (
    <ul className={cn('space-y-1.5', className)} aria-label="Caveats">
      {caveats.map((caveat) => {
        const tone = CAVEAT_TONE[caveat.severity] ?? 'info';
        const rule =
          tone === 'error'
            ? 'border-l-error bg-error-bg'
            : tone === 'warning'
              ? 'border-l-warning bg-warning-bg'
              : 'border-l-info bg-info-bg';
        return (
          <li
            key={caveat.code}
            className={cn('border-l-rule px-3 py-2 text-body text-ink', rule)}
          >
            <div className="flex flex-wrap items-baseline gap-x-2 gap-y-1">
              <span className="font-medium">{caveat.code.replaceAll('_', ' ').toLowerCase()}</span>
              <span className="text-caption text-ink-muted">
                <Figure>{caveat.affected_rows.toLocaleString('en-IN')}</Figure> rows
              </span>
            </div>
            <p className="mt-0.5 text-ink-muted">{caveat.message}</p>
          </li>
        );
      })}
    </ul>
  );
}
