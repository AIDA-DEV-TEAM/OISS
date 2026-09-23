/**
 * Adapter: export service (RFP area 8). Real, as of task 5.
 *
 * A panel sends the query spec that produced it, not the context it believes
 * it has. The backend runs that spec and writes the context it derives from
 * its own execution into the file, so an exported chart can never carry
 * another panel's filters or row count.
 *
 * Surfaces with no single spec to re-run — the dashboard narrative, and
 * panels built from more than one query — send their rows and context as a
 * payload instead. Those files say inside themselves that their context was
 * supplied rather than derived.
 */
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';

import type {
  Caveat,
  ExportFormat,
  ExportRecord,
  ExportType,
  QuerySpec,
} from '@/api/client';
import { api } from '@/api/client';

export interface CreateExportInput {
  exportType: ExportType;
  format: ExportFormat;
  panelTitle: string;
  /** The query behind this panel. Preferred over `payload`. */
  querySpec?: QuerySpec | null;
  /** Rows and context for a panel with no spec. */
  payload?: {
    rows: Array<Record<string, unknown>>;
    context: Record<string, unknown>;
    caveats: Caveat[];
  } | null;
  includeContext?: boolean;
  includeCaveats?: boolean;
  includeRecords?: boolean;
}

export function fetchRecentExports(): Promise<ExportRecord[]> {
  return api.exports({ size: 50 }).then((page) => page.items);
}

export function createExport(input: CreateExportInput): Promise<ExportRecord> {
  return api.createExport({
    export_type: input.exportType,
    format: input.format,
    panel_title: input.panelTitle,
    query_spec: input.querySpec ?? null,
    payload: input.payload ?? null,
    options: {
      include_context: input.includeContext ?? true,
      include_caveats: input.includeCaveats ?? true,
      include_records: input.includeRecords ?? true,
    },
  });
}

/** The href an anchor uses to fetch the generated file. */
export function exportDownloadUrl(exportId: string): string {
  return api.exportDownloadUrl(exportId);
}

/** The service's own row ceiling. It changes only with a deploy, so it is
 *  fetched once and kept. */
export function useExportLimits() {
  return useQuery({
    queryKey: ['export-limits'],
    queryFn: () => api.exportLimits(),
    staleTime: Infinity,
  });
}

export function useRecentExports() {
  return useQuery({ queryKey: ['exports'], queryFn: fetchRecentExports });
}

export function useCreateExport() {
  const client = useQueryClient();
  return useMutation<ExportRecord, Error, CreateExportInput>({
    mutationFn: createExport,
    onSuccess: () => {
      // A completed export belongs at the top of the Exports screen.
      void client.invalidateQueries({ queryKey: ['exports'] });
    },
  });
}
