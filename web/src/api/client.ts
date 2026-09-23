/**
 * Single fetch wrapper for the OISS backend.
 *
 * Every request and response type comes from src/api/types.ts, generated from
 * the backend's OpenAPI document. Nothing here hand-writes a shape, so a
 * backend change surfaces as a compile error rather than a runtime surprise.
 */
import type { components } from '@/api/types';

type Schemas = components['schemas'];

export type Health = Schemas['Health'];
export type DatasetVersion = Schemas['DatasetVersion'];
export type ValidationFinding = Schemas['ValidationFinding'];
export type Lineage = Schemas['Lineage'];
export type LineageEdge = Schemas['LineageEdge'];
export type IngestResult = Schemas['IngestResult'];
export type RuleCount = Schemas['RuleCount'];
export type LayerStage = Schemas['LayerStage'];
export type RuleSummary = Schemas['RuleSummary'];
export type IngestSchema = Schemas['IngestSchema'];
export type ActivationResult = Schemas['ActivationResult'];
export type Caveat = Schemas['Caveat'];
export type AppliedContext = Schemas['AppliedContext'];
export type SourceDataset = Schemas['SourceDataset'];
export type QuerySpec = Schemas['QuerySpec'];
export type QueryResponse = Schemas['QueryResponse'];
export type RecordsResponse = Schemas['RecordsResponse'];
export type NarrativeFactsResponse = Schemas['NarrativeFactsResponse'];
export type MetricInfo = Schemas['MetricInfo'];
export type DimensionInfo = Schemas['DimensionInfo'];
export type DimensionValue = Schemas['DimensionValue'];
export type Filter = Schemas['Filter'];
export type Period = Schemas['Period'];
export type OrderBy = Schemas['OrderBy'];
export type ExportRecord = Schemas['ExportRecord'];
export type ExportLimits = Schemas['ExportLimits'];
export type ExportRequest = Schemas['ExportRequest'];
export type ExportedContext = Schemas['ExportedContext'];
export type ExportOptions = Schemas['ExportOptions'];
export type ExportFormat = ExportRequest['format'];
export type ExportType = ExportRequest['export_type'];
export type SandboxModelConfig = Schemas['SandboxModelConfig'];
export type ModelConfig = Schemas['ModelConfig'];
export type StatedText = Schemas['StatedText'];
export type InputSummary = Schemas['InputSummary'];
export type SandboxDataset = Schemas['SandboxDataset'];
export type SandboxDatasetList = Schemas['SandboxDatasetList'];
export type CreateRunRequest = Schemas['CreateRunRequest'];
export type SandboxRunStatus = Schemas['SandboxRunStatus'];
export type SandboxResults = Schemas['SandboxResults'];
export type SandboxVersion = Schemas['SandboxVersion'];
export type PublishedForecast = Schemas['PublishedForecast'];
export type StarterQuestion = Schemas['StarterQuestion'];
export type AssistantAnswer = Schemas['AssistantAnswer'];
export type Interpretation = Schemas['Interpretation'];
export type ChartSpec = Schemas['ChartSpec'];
export type DescribedFilter = Schemas['DescribedFilter'];
export type DashboardNarrative = Schemas['DashboardNarrative'];
export type NarrativeFact = Schemas['NarrativeFact'];

export type Page<T> = { items: T[]; total: number; page: number; size: number };

/** The backend's error body: { detail, code }, plus field/allowed_values on 422. */
export interface ApiErrorBody {
  detail: string;
  code: string;
  field?: string;
  allowed_values?: string[];
}

export class ApiError extends Error {
  readonly status: number;
  readonly code: string;
  readonly field?: string;
  readonly allowedValues?: string[];

  constructor(status: number, body: ApiErrorBody) {
    super(body.detail);
    this.name = 'ApiError';
    this.status = status;
    this.code = body.code;
    this.field = body.field;
    this.allowedValues = body.allowed_values;
  }
}

/** Raised when the backend cannot be reached at all, which reads differently
 *  to a rejected request and is shown differently. */
export class BackendUnreachableError extends Error {
  constructor(cause: unknown) {
    super('The backend did not respond.');
    this.name = 'BackendUnreachableError';
    this.cause = cause;
  }
}

const BASE = '/api';

async function parseError(response: Response): Promise<never> {
  let body: ApiErrorBody = {
    detail: `Request failed with status ${response.status}.`,
    code: 'unexpected_error',
  };
  try {
    const parsed: unknown = await response.json();
    if (parsed && typeof parsed === 'object' && 'detail' in parsed) {
      body = parsed as ApiErrorBody;
    }
  } catch {
    // A non-JSON error body stays as the generic message above.
  }
  throw new ApiError(response.status, body);
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  let response: Response;
  try {
    response = await fetch(`${BASE}${path}`, init);
  } catch (cause) {
    throw new BackendUnreachableError(cause);
  }
  if (!response.ok) await parseError(response);
  return (await response.json()) as T;
}

function query(params: Record<string, string | number | boolean | undefined>): string {
  const search = new URLSearchParams();
  for (const [key, value] of Object.entries(params)) {
    if (value !== undefined && value !== '') search.set(key, String(value));
  }
  const rendered = search.toString();
  return rendered ? `?${rendered}` : '';
}

export const api = {
  health: () => request<Health>('/health'),

  datasets: (params: { page?: number; size?: number; layer?: string } = {}) =>
    request<Page<DatasetVersion>>(`/datasets${query({ size: 200, ...params })}`),

  dataset: (versionId: string) =>
    request<DatasetVersion>(`/datasets/${encodeURIComponent(versionId)}`),

  findings: (
    versionId: string,
    params: { page?: number; size?: number; severity?: string; rule_code?: string } = {},
  ) =>
    request<Page<ValidationFinding>>(
      `/datasets/${encodeURIComponent(versionId)}/validation${query(params)}`,
    ),

  validationSummary: (versionId: string) =>
    request<Page<RuleSummary>>(
      `/datasets/${encodeURIComponent(versionId)}/validation/summary`,
    ),

  layers: (versionId: string) =>
    request<Page<LayerStage>>(`/datasets/${encodeURIComponent(versionId)}/layers`),

  lineage: (versionId: string) =>
    request<Lineage>(`/lineage/${encodeURIComponent(versionId)}`),

  upload: (
    datasetName: string,
    file: File | Blob,
    filename: string,
    dataOrigin?: string,
  ) => {
    const form = new FormData();
    form.set('dataset_name', datasetName);
    // Declared by the uploader for a file with no registered schema; a
    // registered dataset declares its own and this is ignored.
    if (dataOrigin) form.set('data_origin', dataOrigin);
    form.set('file', file, filename);
    return request<IngestResult>('/ingest/upload', { method: 'POST', body: form });
  },

  ingestSchemas: () => request<Page<IngestSchema>>('/ingest/schemas'),

  setActive: (versionId: string, active: boolean) =>
    request<ActivationResult>(
      `/datasets/${encodeURIComponent(versionId)}/${active ? 'activate' : 'deactivate'}`,
      { method: 'POST' },
    ),

  metrics: () => request<Page<MetricInfo>>('/semantic/metrics'),

  dimensions: () => request<Page<DimensionInfo>>('/semantic/dimensions'),

  dimensionValues: (dimensionId: string, params: { page?: number; size?: number } = {}) =>
    request<Page<DimensionValue>>(
      `/semantic/dimensions/${encodeURIComponent(dimensionId)}/values${query(params)}`,
    ),

  query: (spec: QuerySpec) =>
    request<QueryResponse>('/query', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(spec),
    }),

  records: (spec: QuerySpec) =>
    request<RecordsResponse>('/query/records', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(spec),
    }),

  narrativeFacts: (spec: QuerySpec) =>
    request<NarrativeFactsResponse>('/query/narrative-facts', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(spec),
    }),

  createExport: (body: ExportRequest) =>
    request<ExportRecord>('/export', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    }),

  exportLimits: () => request<ExportLimits>('/exports/limits'),

  exports: (params: { page?: number; size?: number } = {}) =>
    request<Page<ExportRecord>>(`/exports${query(params)}`),

  /** Where the browser fetches the generated file. Not a JSON call, so it
   *  bypasses `request` and is used as an anchor href. */
  exportDownloadUrl: (exportId: string) =>
    `${BASE}/export/${encodeURIComponent(exportId)}/download`,

  // --------------------------------------------------------------------------
  // Sandbox & Forecasting (Task 7)
  // --------------------------------------------------------------------------
  sandboxModelConfig: () => request<SandboxModelConfig>('/sandbox/model-config'),

  sandboxDatasets: () => request<SandboxDatasetList>('/sandbox/datasets'),

  createSandboxRun: (payload: CreateRunRequest) =>
    request<SandboxRunStatus>('/sandbox/runs', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    }),

  sandboxRunStatus: (runId: string) =>
    request<SandboxRunStatus>(`/sandbox/runs/${encodeURIComponent(runId)}`),

  sandboxRunResults: (runId: string) =>
    request<SandboxResults>(`/sandbox/runs/${encodeURIComponent(runId)}/results`),

  saveSandboxVersion: (runId: string, label: string) =>
    request<SandboxVersion>(`/sandbox/runs/${encodeURIComponent(runId)}/versions`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ label }),
    }),

  publishSandboxVersion: (versionId: string) =>
    request<{ version_id: string; published: boolean }>(
      `/sandbox/versions/${encodeURIComponent(versionId)}/publish`,
      { method: 'POST' },
    ),

  dashboardForecasts: () => request<PublishedForecast[]>('/dashboard/forecasts'),

  narrative: (spec: QuerySpec) =>
    request<DashboardNarrative>('/narrative/dashboard', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ query_spec: spec }),
    }),

  assistantQuestions: () => request<Page<StarterQuestion>>('/assistant/questions'),

  ask: (question: string) =>
    request<AssistantAnswer>('/assistant/ask', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ question }),
    }),
};
