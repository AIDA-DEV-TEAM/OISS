/**
 * Export dialog — RFP area 8.
 *
 * Reachable from every panel. Task 5's rule is that an export carries its
 * applied context, so the dialog previews exactly what will travel with the
 * file — filters, period, row count, dataset versions, origin mix and caveats —
 * before anything is generated.
 *
 * Replaces ExportModalStub and its dual `open`/`isOpen` prop pair with one
 * spelling.
 */
import { useEffect, useState } from 'react';

import type { ExportContext, ExportFormat, ExportType } from '@/api/contracts';
import { useCreateExport } from '@/api/exports';
import { CaveatList } from '@/components/provenance';
import { Figure, cn } from '@/components/primitives';
import { ProvenanceNote } from '@/components/ProvenanceNote';
import { ErrorState } from '@/components/states';
import { formatBytes } from '@/lib/format';

const FORMATS: Array<{ id: ExportFormat; label: string; detail: string }> = [
  { id: 'csv', label: 'CSV', detail: 'Rows plus a companion context file.' },
  { id: 'xlsx', label: 'Excel', detail: 'Data, Context and Caveats as separate sheets.' },
  { id: 'pdf', label: 'PDF', detail: 'Titled report with caveats as footnotes.' },
  { id: 'json', label: 'JSON', detail: 'The query response verbatim, context included.' },
  { id: 'png', label: 'Chart image', detail: 'Rendered server-side from the same result.' },
];

export interface ExportModalProps {
  open: boolean;
  onClose: () => void;
  exportType: ExportType;
  context: ExportContext | null;
}

export function ExportModal({ open, onClose, exportType, context }: ExportModalProps) {
  const [format, setFormat] = useState<ExportFormat>('csv');
  const [includeContext, setIncludeContext] = useState(true);
  const [includeCaveats, setIncludeCaveats] = useState(true);
  const [includeRecords, setIncludeRecords] = useState(true);
  const create = useCreateExport();

  // Re-open on a different panel starts a fresh dialog, not the last result.
  useEffect(() => {
    if (open) create.reset();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open]);

  useEffect(() => {
    if (!open) return;
    function onKey(event: KeyboardEvent) {
      if (event.key === 'Escape') onClose();
    }
    document.addEventListener('keydown', onKey);
    return () => document.removeEventListener('keydown', onKey);
  }, [open, onClose]);

  if (!open || !context) return null;

  const tabular = format !== 'png';
  const result = create.data;

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center p-4">
      <div className="absolute inset-0 bg-ink/20" onClick={onClose} aria-hidden="true" />
      <div
        role="dialog"
        aria-modal="true"
        aria-labelledby="export-title"
        className="relative flex max-h-dialog w-full max-w-2xl flex-col rounded-card border border-line bg-surface shadow-drawer"
      >
        <header className="flex items-start justify-between gap-4 border-b border-line px-card py-3">
          <div className="min-w-0">
            <h2 id="export-title" className="text-title font-semibold text-ink">
              Export
            </h2>
            <p className="mt-0.5 truncate text-caption text-ink-muted">
              {context.panel_title}
            </p>
            <ProvenanceNote
              className="mt-0.5"
              signals={{ dataOrigin: context.data_origin, grainSource: context.grain_source }}
            />
          </div>
          <button
            type="button"
            onClick={onClose}
            className="shrink-0 rounded border border-line bg-surface px-2 py-1 text-body text-ink-muted transition-colors duration-state hover:bg-surface-alt hover:text-ink"
          >
            Close
          </button>
        </header>

        <div className="flex-1 overflow-auto px-card py-card">
          {result ? (
            <div className="rounded border border-success/30 bg-success-bg px-card py-4">
              <p className="text-body font-medium text-success">Export ready</p>
              <p className="mt-1 break-all text-body text-ink">{result.filename}</p>
              <p className="mt-0.5 text-caption text-ink-muted">
                <Figure>{formatBytes(result.size_bytes)}</Figure> · reference{' '}
                <Figure>{result.export_id}</Figure> · context attached
              </p>
              <button
                type="button"
                className="mt-3 rounded border border-primary bg-primary px-3 py-1.5 text-body font-medium text-surface transition-colors duration-state hover:bg-primary-hover"
              >
                Download
              </button>
            </div>
          ) : (
            <>
              <fieldset>
                <legend className="text-caption font-medium uppercase tracking-header text-ink-subtle">
                  Format
                </legend>
                <div className="mt-2 grid grid-cols-1 gap-2 sm:grid-cols-2">
                  {FORMATS.map((option) => (
                    <label
                      key={option.id}
                      className={cn(
                        'flex cursor-pointer items-start gap-2 rounded border px-3 py-2 transition-colors duration-state',
                        format === option.id
                          ? 'border-primary bg-primary-subtle'
                          : 'border-line bg-surface hover:bg-surface-alt',
                      )}
                    >
                      <input
                        type="radio"
                        name="export-format"
                        value={option.id}
                        checked={format === option.id}
                        onChange={() => setFormat(option.id)}
                        className="mt-1"
                      />
                      <span className="min-w-0">
                        <span className="block text-body font-medium text-ink">{option.label}</span>
                        <span className="block text-caption text-ink-muted">{option.detail}</span>
                      </span>
                    </label>
                  ))}
                </div>
              </fieldset>

              <fieldset className="mt-4">
                <legend className="text-caption font-medium uppercase tracking-header text-ink-subtle">
                  Options
                </legend>
                <div className="mt-2 space-y-2">
                  <Option
                    label="Include applied context"
                    detail="Filters, period, dataset versions and origin mix."
                    checked={includeContext}
                    onChange={setIncludeContext}
                  />
                  <Option
                    label="Include caveats"
                    detail="Every caveat that applies to this selection."
                    checked={includeCaveats}
                    onChange={setIncludeCaveats}
                  />
                  <Option
                    label="Include records"
                    detail={
                      tabular
                        ? 'The underlying fact rows behind the figures.'
                        : 'A chart image carries no rows.'
                    }
                    checked={tabular && includeRecords}
                    disabled={!tabular}
                    onChange={setIncludeRecords}
                  />
                </div>
              </fieldset>

              <section className="mt-4 rounded border border-line bg-surface-alt px-card py-3">
                <h3 className="text-caption font-medium uppercase tracking-header text-ink-subtle">
                  Context that travels with the file
                </h3>
                <dl className="mt-2 grid grid-cols-1 gap-x-gutter gap-y-2 sm:grid-cols-2">
                  <Pair term="Rows">
                    <Figure>{context.row_count.toLocaleString('en-IN')}</Figure>
                  </Pair>
                  <Pair term="Period">{context.period ?? '—'}</Pair>
                  <Pair term="Filters">
                    {context.filters.length === 0
                      ? 'None'
                      : context.filters
                          .map((f) => `${f.dimension}: ${f.values.join(', ')}`)
                          .join(' · ')}
                  </Pair>
                  <Pair term="Source datasets">
                    {context.source_datasets.length === 0
                      ? 'None'
                      : context.source_datasets.map((d) => d.dataset_name).join(', ')}
                  </Pair>
                </dl>
                {context.caveats.length > 0 && (
                  <CaveatList className="mt-3" caveats={context.caveats} />
                )}
              </section>

              {create.isError && (
                <div className="mt-3">
                  <ErrorState error={create.error} compact />
                </div>
              )}
            </>
          )}
        </div>

        {!result && (
          <footer className="flex items-center justify-end gap-2 border-t border-line px-card py-3">
            <button
              type="button"
              onClick={onClose}
              className="rounded border border-line bg-surface px-3 py-1.5 text-body text-ink-muted transition-colors duration-state hover:bg-surface-alt hover:text-ink"
            >
              Cancel
            </button>
            <button
              type="button"
              disabled={create.isPending}
              onClick={() =>
                create.mutate({
                  export_type: exportType,
                  format,
                  context: {
                    ...context,
                    caveats: includeCaveats ? context.caveats : [],
                  },
                })
              }
              className="rounded border border-primary bg-primary px-3 py-1.5 text-body font-medium text-surface transition-colors duration-state hover:bg-primary-hover disabled:opacity-60"
            >
              {create.isPending ? 'Preparing…' : 'Export'}
            </button>
          </footer>
        )}
      </div>
    </div>
  );
}

function Option({
  label,
  detail,
  checked,
  disabled = false,
  onChange,
}: {
  label: string;
  detail: string;
  checked: boolean;
  disabled?: boolean;
  onChange: (next: boolean) => void;
}) {
  return (
    <label
      className={cn(
        'flex items-start gap-2',
        disabled ? 'cursor-not-allowed opacity-60' : 'cursor-pointer',
      )}
      title={disabled ? detail : undefined}
    >
      <input
        type="checkbox"
        checked={checked}
        disabled={disabled}
        onChange={(event) => onChange(event.target.checked)}
        className="mt-1"
      />
      <span>
        <span className="block text-body text-ink">{label}</span>
        <span className="block text-caption text-ink-muted">{detail}</span>
      </span>
    </label>
  );
}

function Pair({ term, children }: { term: string; children: React.ReactNode }) {
  return (
    <div className="min-w-0">
      <dt className="text-caption font-medium text-ink-muted">{term}</dt>
      <dd className="mt-0.5 break-words text-body text-ink">{children}</dd>
    </div>
  );
}
