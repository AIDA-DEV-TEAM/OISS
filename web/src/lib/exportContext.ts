/**
 * Builds the context an export carries with it.
 *
 * Task 5's rule: a file that leaves the system without its filters, period,
 * dataset versions, origin mix and caveats is a file nobody can defend six
 * months later. Every panel therefore assembles its context the same way,
 * through here, rather than each inventing its own shape.
 */
import type { AppliedContext, Caveat, QuerySpec, SourceDataset } from '@/api/client';

type SourceRef = Pick<SourceDataset, 'dataset_name' | 'dataset_version_id'>;

/**
 * A filter as the backend describes it. `dimension_label` and `values_display`
 * ("Crop", "Paddy (CR17)") come from the masters on the server; nothing here
 * works them out. A filter built by a surface with no backend context has
 * only the raw fields, and is shown as it is.
 */
export interface FilterDescription {
  dimension: string;
  values: string[];
  dimension_label?: string;
  values_display?: string[];
}

/** "Crop: Paddy (CR17)" — the backend's wording, or the raw values if none came. */
export function filterPhrase(filter: {
  dimension?: unknown;
  values?: unknown;
  dimension_label?: unknown;
  values_display?: unknown;
}): string {
  const label = typeof filter.dimension_label === 'string'
    ? filter.dimension_label
    : String(filter.dimension ?? '');
  const shown = Array.isArray(filter.values_display)
    ? filter.values_display
    : Array.isArray(filter.values)
      ? filter.values
      : [];
  return `${label}: ${shown.map(String).join(', ')}`;
}

/** "Potato (CR18)": the crop a query filtered to, as the backend describes it. */
export function cropDisplayName(applied: AppliedContext | null | undefined): string | null {
  const filter = applied?.filters?.find((f) => f.dimension === 'crop');
  const shown = filter?.values_display ?? filter?.values;
  return Array.isArray(shown) && shown.length === 1 ? String(shown[0]) : null;
}

/**
 * What a panel shows in the export dialog, and what it sends as a payload when
 * it has no query spec to send instead.
 */
export interface ExportContext {
  panel_title: string;
  filters: FilterDescription[];
  period?: string | null;
  row_count: number;
  underlying_row_count?: number;
  truncated?: boolean;
  matching_row_count?: number | null;
  source_datasets: SourceRef[];
  data_origin: Record<string, number>;
  grain_source?: Record<string, number>;
  caveats: Caveat[];
}

/**
 * One panel's export, as the panel hands it to the dialog.
 *
 * `spec` is the point: the panel passes the query that actually produced it,
 * so the backend re-runs that query and the file's context describes the
 * file's own rows. A panel with no spec falls back to `context` and `rows`,
 * and the resulting file says its context was supplied rather than derived.
 */
export interface PanelExport {
  title: string;
  spec?: QuerySpec | null;
  context: ExportContext;
  rows?: Array<Record<string, unknown>>;
}

export function toExportContext(input: {
  panelTitle: string;
  filters?: Array<{ dimension: string; values: string[] }>;
  period?: string | null;
  rowCount?: number;
  underlyingRowCount?: number;
  truncated?: boolean;
  matchingRowCount?: number | null;
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
    underlying_row_count: input.underlyingRowCount,
    truncated: input.truncated,
    matching_row_count: input.matchingRowCount,
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
      const display = record.values_display;
      return {
        dimension: String(record.dimension ?? ''),
        values: Array.isArray(values) ? values.map(String) : [],
        // Carried through as sent, so the dialog quotes the server's labels.
        dimension_label:
          typeof record.dimension_label === 'string' ? record.dimension_label : undefined,
        values_display: Array.isArray(display) ? display.map(String) : undefined,
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
