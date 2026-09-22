/**
 * Adapter: guided sandbox and the crop-yield preset (RFP areas 6 and 7).
 *
 * Mocked until task 7 builds the /sandbox/* adapter in the backend. The wizard
 * treats a run as a job with a polled status even though the mock resolves
 * instantly, so swapping in the real endpoints needs no UI change.
 */
import { useMutation, useQuery } from '@tanstack/react-query';

import type {
  SandboxColumn,
  SandboxDataset,
  SandboxResults,
  SandboxRunStatus,
  SandboxUseCase,
  SandboxVersion,
} from '@/api/contracts';
import { USE_MOCKS } from '@/mocks/config';
import {
  mockCreateRun,
  mockPublishVersion,
  mockRunResults,
  mockRunStatus,
  mockSandboxColumns,
  mockSandboxDatasets,
  mockSaveVersion,
  mockUseCases,
} from '@/mocks/sandbox';

export function fetchUseCases(): Promise<SandboxUseCase[]> {
  if (USE_MOCKS) return mockUseCases();
  throw new Error('GET /sandbox/use-cases is not implemented yet (task 7).');
}

export function fetchSandboxDatasets(): Promise<SandboxDataset[]> {
  if (USE_MOCKS) return mockSandboxDatasets();
  throw new Error('GET /sandbox/datasets is not implemented yet (task 7).');
}

export function fetchSandboxColumns(datasetId: string): Promise<SandboxColumn[]> {
  if (USE_MOCKS) return mockSandboxColumns();
  throw new Error(`GET /sandbox/datasets/${datasetId}/columns is not implemented yet (task 7).`);
}

export function createRun(): Promise<{ run_id: string }> {
  if (USE_MOCKS) return mockCreateRun();
  throw new Error('POST /sandbox/runs is not implemented yet (task 7).');
}

/** `poll` is the poll index; the real endpoint ignores it and reads the row. */
export function fetchRunStatus(runId: string, poll: number): Promise<SandboxRunStatus> {
  if (USE_MOCKS) return mockRunStatus(poll);
  throw new Error(`GET /sandbox/runs/${runId} is not implemented yet (task 7).`);
}

export function fetchRunResults(runId: string): Promise<SandboxResults> {
  if (USE_MOCKS) return mockRunResults();
  throw new Error(`GET /sandbox/runs/${runId}/results is not implemented yet (task 7).`);
}

export function saveVersion(runId: string, label: string): Promise<SandboxVersion> {
  if (USE_MOCKS) return mockSaveVersion(runId, label);
  throw new Error('POST /sandbox/runs/{id}/versions is not implemented yet (task 7).');
}

export function publishVersion(versionId: string): Promise<{ version_id: string; published: true }> {
  if (USE_MOCKS) return mockPublishVersion(versionId);
  throw new Error('POST /sandbox/versions/{id}/publish is not implemented yet (task 7).');
}

export function useUseCases() {
  return useQuery({ queryKey: ['sandbox-use-cases'], queryFn: fetchUseCases });
}

export function useSandboxDatasets() {
  return useQuery({ queryKey: ['sandbox-datasets'], queryFn: fetchSandboxDatasets });
}

export function useSandboxColumns(datasetId: string | undefined) {
  return useQuery({
    queryKey: ['sandbox-columns', datasetId ?? ''],
    queryFn: () => fetchSandboxColumns(datasetId as string),
    enabled: Boolean(datasetId),
  });
}

export function useRunResults(runId: string | undefined) {
  return useQuery({
    queryKey: ['sandbox-results', runId ?? ''],
    queryFn: () => fetchRunResults(runId as string),
    enabled: Boolean(runId),
  });
}

export function useSaveVersion() {
  return useMutation<SandboxVersion, Error, { runId: string; label: string }>({
    mutationFn: ({ runId, label }) => saveVersion(runId, label),
  });
}

export function usePublishVersion() {
  return useMutation<{ version_id: string; published: true }, Error, string>({
    mutationFn: (versionId) => publishVersion(versionId),
  });
}
