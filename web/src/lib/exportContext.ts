/**
 * Builds the context an export carries with it.
 *
 * Task 5's rule: a file that leaves the system without its filters, period,
 * dataset versions, origin mix and caveats is a file nobody can defend six
 * months later. Every panel therefore assembles its context the same way,
 * through here, rather than each inventing its own shape.
 */
import type { AppliedContext, Caveat, SourceDataset } from '@/api/client';
import type { ExportContext } from '@/api/contracts';

type SourceRef = Pick<SourceDataset, 'dataset_name' | 'dataset_version_id'>;

export function toExportContext(input: {
  panelTitle: string;
  filters?: Array<{ dimension: string; values: string[] }>;
  period?: string | null;
  rowCount?: number;
  sources?: SourceRef[];
  dataOrigin?: Record<string, number>;
  grainSource?: Record<string, number>;
  caveats?: Caveat[];
}): ExportContext {
  return {
    panel_title: input.panelTitle,
    filters: input.filters ?? [],
    period: input.period ?? null,
    row_count: input.rowCount ?? 0,
    source_datasets: input.sources ?? [],
    data_origin: input.dataOrigin ?? {},
    grain_source: input.grainSource,
    caveats: input.caveats ?? [],
  };
}

/** The backend's period object as a phrase, never as raw JSON on screen. */
function formatPeriod(period: AppliedContext['period']): string | null {
  if (!period) return null;
  const record = period as Record<string, unknown>;
  const from = record.from ?? record.start;
  const to = record.to ?? record.end;
  if (from && to) return from === to ? String(from) : `${String(from)} to ${String(to)}`;
  if (from) return `from ${String(from)}`;
  if (to) return `to ${String(to)}`;
  const values = Object.values(record).filter(Boolean).map(String);
  return values.length > 0 ? values.join(' · ') : null;
}

/** The same thing, straight from a backend query response. */
export function contextFromApplied(
  panelTitle: string,
  applied: AppliedContext | null | undefined,
  caveats: Caveat[] = [],
): ExportContext {
  if (!applied) return toExportContext({ panelTitle });
  return {
    panel_title: panelTitle,
    filters: (applied.filters ?? []).map((filter) => {
      const record = filter as Record<string, unknown>;
      const values = record.values;
      return {
        dimension: String(record.dimension ?? ''),
        values: Array.isArray(values) ? values.map(String) : [],
      };
    }),
    period: formatPeriod(applied.period),
    row_count: applied.row_count,
    source_datasets: applied.source_datasets.map((source) => ({
      dataset_name: source.dataset_name,
      dataset_version_id: source.dataset_version_id,
    })),
    data_origin: applied.data_origin,
    grain_source: applied.grain_source,
    caveats,
  };
}
