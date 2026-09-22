/**
 * Response shapes for the endpoints tasks 5, 6 and 7 will build.
 *
 * These mirror the contracts in docs/handoff/claude_code_prompt_5_exports.md,
 * _6_genai.md and _7_sandbox.md. Mocks are typed against them, so when a real
 * endpoint lands the adapter swaps over without touching a component.
 *
 * Types for endpoints that already exist are generated into src/api/types.ts
 * from the OpenAPI document and are never hand-written.
 */
import type { Caveat, SourceDataset } from '@/api/client';

// --------------------------------------------------------------------------
// Task 6 — GenAI narrative and assistant
// --------------------------------------------------------------------------

/** One number the narrative is allowed to quote, with where it came from. */
export interface NarrativeFact {
  label: string;
  value: number | null;
  unit: string;
  /** Dimension values this fact is scoped to, e.g. "Winter, 2024-25". */
  scope?: string;
}

/** POST /narrative/dashboard */
export interface DashboardNarrative {
  narrative: string;
  facts_used: NarrativeFact[];
  caveats: Caveat[];
  served_from_cache: boolean;
  /** Mirrors applied_context.data_origin so disclosure is field-driven. */
  data_origin: Record<string, number>;
  grain_source?: Record<string, number>;
}

export interface AssistantChartSpec {
  kind: 'bar' | 'line';
  x_key: string;
  y_key: string;
  unit: string;
  series_label: string;
  data: Array<Record<string, string | number | null>>;
}

/** POST /assistant/ask */
export interface AssistantAnswer {
  question_id: string;
  question: string;
  /** A declined answer carries no chart and no records. */
  status: 'answered' | 'declined';
  answer: string;
  /** Present when the assistant declines: what it could not do, and why. */
  limitation?: string;
  chart_spec?: AssistantChartSpec | null;
  applied_filters: Array<{ dimension: string; values: string[] }>;
  source_datasets: Array<Pick<SourceDataset, 'dataset_name' | 'dataset_version_id'>>;
  period?: string | null;
  records_preview: Array<Record<string, string | number | null>>;
  caveats: Caveat[];
  served_from_cache: boolean;
  data_origin: Record<string, number>;
  grain_source?: Record<string, number>;
}

// --------------------------------------------------------------------------
// Task 7 — sandbox
// --------------------------------------------------------------------------

export interface SandboxUseCase {
  id: string;
  label: string;
  description: string;
  /** The crop-yield scenario is the default preset (RFP area 6 inside 7). */
  is_default: boolean;
}

export interface SandboxDataset {
  dataset_id: string;
  label: string;
  years: string;
  grain: string;
  row_count: number;
}

export interface SandboxColumn {
  name: string;
  label: string;
  dtype: 'numeric' | 'categorical';
  /** Whether it may be picked as the target, a feature, or neither. */
  role: 'target' | 'feature' | 'both' | 'identifier';
}

export type RunStatus = 'queued' | 'running' | 'completed' | 'failed';

/** GET /sandbox/runs/{id} */
export interface SandboxRunStatus {
  run_id: string;
  status: RunStatus;
  /** 0–100. */
  progress: number;
  message: string;
}

export interface MetricSet {
  r2: number;
  rmse: number;
  mae: number;
  n: number;
}

export interface PerCropMetric extends MetricSet {
  crop_id: string;
  crop_name: string;
}

export interface ActualVsPredicted {
  district_name: string;
  crop_name: string;
  actual: number;
  predicted: number;
  residual: number;
}

export interface FeatureImportance {
  feature: string;
  label: string;
  weight: number;
}

export interface PredictionRow {
  district_id: string;
  district_name: string;
  crop_id: string;
  crop_name: string;
  season: string;
  area_ha: number;
  predicted_yield_qtl_per_ha: number;
  estimated_production_qtls: number;
  output_label: string;
}

/** GET /sandbox/runs/{id}/results */
export interface SandboxResults {
  run_id: string;
  pooled: MetricSet;
  per_crop: PerCropMetric[];
  actual_vs_predicted: ActualVsPredicted[];
  feature_importance: FeatureImportance[];
  explanation: string;
  predictions: PredictionRow[];
  /** Model output, so every consumer discloses it the same way. */
  data_origin: Record<string, number>;
  served_from_cache: boolean;
}

export interface SandboxVersion {
  version_id: string;
  run_id: string;
  label: string;
  created_at: string;
  published: boolean;
  parameters: Record<string, string>;
}

// --------------------------------------------------------------------------
// Task 7 — published forecasts feeding the dashboard panel
// --------------------------------------------------------------------------

/** GET /dashboard/forecasts */
export interface PublishedForecast {
  crop_id: string;
  crop_name: string;
  district_id: string;
  district_name: string;
  season: string;
  agri_year: string;
  actual_yield: number | null;
  forecast_yield: number;
  unit: string;
  version_id: string;
  output_label: string;
  data_origin: Record<string, number>;
}

// --------------------------------------------------------------------------
// Task 5 — exports
// --------------------------------------------------------------------------

export type ExportFormat = 'csv' | 'xlsx' | 'pdf' | 'json' | 'png';

export type ExportType =
  | 'dashboard_panel'
  | 'records_grid'
  | 'assistant_answer'
  | 'model_output'
  | 'narrative';

export interface ExportOptions {
  include_context: boolean;
  include_caveats: boolean;
  /** Only meaningful for tabular formats. */
  include_records: boolean;
}

/** The context an export carries with it, per task 5's central rule. */
export interface ExportContext {
  panel_title: string;
  filters: Array<{ dimension: string; values: string[] }>;
  period?: string | null;
  row_count: number;
  source_datasets: Array<Pick<SourceDataset, 'dataset_name' | 'dataset_version_id'>>;
  data_origin: Record<string, number>;
  grain_source?: Record<string, number>;
  caveats: Caveat[];
}

/** A row of GET /exports */
export interface ExportRecord {
  export_id: string;
  export_type: ExportType;
  format: ExportFormat;
  status: 'queued' | 'running' | 'completed' | 'failed';
  filename: string;
  size_bytes: number;
  created_at: string;
  context: ExportContext;
}
