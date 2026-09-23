/**
 * Adapter: guided sandbox and the crop-yield preset (RFP areas 6 and 7).
 *
 * Real, wired to /sandbox/* endpoints (Task 7).
 */
import { useMutation, useQuery } from '@tanstack/react-query';

import { api } from '@/api/client';
import type {
  CreateRunRequest,
  SandboxDatasetList,
  SandboxModelConfig,
  SandboxResults,
  SandboxRunStatus,
  SandboxVersion,
} from '@/api/client';

export function fetchModelConfig(): Promise<SandboxModelConfig> {
  return api.sandboxModelConfig();
}

export function fetchSandboxDatasets(): Promise<SandboxDatasetList> {
  return api.sandboxDatasets();
}

/** Blocks until the run has ended: the backend runs it within the request. */
export function createRun(payload: CreateRunRequest): Promise<SandboxRunStatus> {
  return api.createSandboxRun(payload);
}

export function fetchRunStatus(runId: string): Promise<SandboxRunStatus> {
  return api.sandboxRunStatus(runId);
}

export function fetchRunResults(runId: string): Promise<SandboxResults> {
  return api.sandboxRunResults(runId);
}

export function saveVersion(runId: string, label: string): Promise<SandboxVersion> {
  return api.saveSandboxVersion(runId, label);
}

export function publishVersion(versionId: string): Promise<{ version_id: string; published: true }> {
  return api.publishSandboxVersion(versionId) as Promise<{ version_id: string; published: true }>;
}

export function useModelConfig() {
  return useQuery({ queryKey: ['sandbox-model-config'], queryFn: fetchModelConfig });
}

export function useSandboxDatasets() {
  return useQuery({ queryKey: ['sandbox-datasets'], queryFn: fetchSandboxDatasets });
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

