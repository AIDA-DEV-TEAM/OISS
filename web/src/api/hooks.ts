/** TanStack Query hooks. Components never call fetch directly. */
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';

import { api } from '@/api/client';
import type { IngestResult } from '@/api/client';

export const keys = {
  health: ['health'] as const,
  datasets: ['datasets'] as const,
  dataset: (id: string) => ['dataset', id] as const,
  findings: (id: string, severity?: string, rule?: string, page?: number) =>
    ['findings', id, severity ?? 'all', rule ?? 'all', page ?? 1] as const,
  validationSummary: (id: string) => ['validation-summary', id] as const,
  layers: (id: string) => ['layers', id] as const,
  lineage: (id: string) => ['lineage', id] as const,
  ingestSchemas: ['ingest-schemas'] as const,
};

export function useHealth() {
  return useQuery({
    queryKey: keys.health,
    queryFn: api.health,
    // The banner should notice a backend that has gone away mid-demo.
    refetchInterval: 30_000,
    retry: 1,
  });
}

export function useDatasets() {
  return useQuery({ queryKey: keys.datasets, queryFn: () => api.datasets() });
}

export function useDataset(versionId: string | undefined) {
  return useQuery({
    queryKey: keys.dataset(versionId ?? ''),
    queryFn: () => api.dataset(versionId as string),
    enabled: Boolean(versionId),
  });
}

export function useValidationSummary(versionId: string | undefined) {
  return useQuery({
    queryKey: keys.validationSummary(versionId ?? ''),
    queryFn: () => api.validationSummary(versionId as string),
    enabled: Boolean(versionId),
  });
}

export function useFindings(
  versionId: string | undefined,
  options: { severity?: string; ruleCode?: string; page?: number; size?: number } = {},
) {
  const { severity, ruleCode, page = 1, size = 50 } = options;
  return useQuery({
    queryKey: keys.findings(versionId ?? '', severity, ruleCode, page),
    queryFn: () =>
      api.findings(versionId as string, { severity, rule_code: ruleCode, page, size }),
    enabled: Boolean(versionId),
    placeholderData: (previous) => previous,
  });
}

export function useLayers(versionId: string | undefined) {
  return useQuery({
    queryKey: keys.layers(versionId ?? ''),
    queryFn: () => api.layers(versionId as string),
    enabled: Boolean(versionId),
  });
}

export function useLineage(versionId: string | undefined) {
  return useQuery({
    queryKey: keys.lineage(versionId ?? ''),
    queryFn: () => api.lineage(versionId as string),
    enabled: Boolean(versionId),
  });
}

export function useIngestSchemas() {
  return useQuery({
    queryKey: keys.ingestSchemas,
    queryFn: api.ingestSchemas,
    // Declared schemas change only when the code does.
    staleTime: Infinity,
  });
}

export function useUpload() {
  const client = useQueryClient();
  return useMutation<
    IngestResult,
    Error,
    { datasetName: string; file: File | Blob; filename: string }
  >({
    mutationFn: ({ datasetName, file, filename }) =>
      api.upload(datasetName, file, filename),
    onSuccess: () => {
      // An upload registers a new dataset version, so the picker is stale.
      void client.invalidateQueries({ queryKey: keys.datasets });
    },
  });
}
