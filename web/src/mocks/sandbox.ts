/**
 * Guided sandbox: use cases, dataset columns, run lifecycle and results
 * (RFP areas 6 and 7).
 *
 * Feeds: SandboxPage → every wizard step.
 * Replace with: GET /sandbox/use-cases, /sandbox/datasets,
 * /sandbox/datasets/{id}/columns, POST /sandbox/runs, GET /sandbox/runs/{id},
 * GET /sandbox/runs/{id}/results, POST /sandbox/runs/{id}/versions,
 * POST /sandbox/versions/{id}/publish (task 7).
 *
 * The metrics mirror what the teammate's model service reports: pooled R² of
 * 0.661, trained on one year (2024-25) with no time dimension. Prompt 7 is
 * explicit that the pooled figure is dominated by differences between crops, so
 * the per-crop table is the honest view and the UI makes no accuracy claim.
 */
import { mockDelay } from '@/mocks/config';
import type {
  ActualVsPredicted,
  FeatureImportance,
  PerCropMetric,
  PredictionRow,
  SandboxColumn,
  SandboxDataset,
  SandboxResults,
  SandboxRunStatus,
  SandboxUseCase,
  SandboxVersion,
} from '@/api/contracts';

export const MOCK_USE_CASES: SandboxUseCase[] = [
  {
    id: 'minor_crop_yield',
    label: 'Minor-crop yield estimation',
    description:
      'Estimate yield in quintals per hectare for a minor crop given district, season and sown area.',
    is_default: true,
  },
  {
    id: 'production_gap',
    label: 'District production gap',
    description: 'Compare district production against the state rate for the same crop and season.',
    is_default: false,
  },
  {
    id: 'land_use_share',
    label: 'Land-use share projection',
    description: 'Project net sown area as a share of surveyed area from the nine-fold split.',
    is_default: false,
  },
];

export const MOCK_DATASETS: SandboxDataset[] = [
  {
    dataset_id: 'earas_2024_25_district_crop_ayp',
    label: 'EARAS district crop area, yield and production',
    years: '2024-25',
    grain: 'district × crop × season',
    row_count: 5456,
  },
  {
    dataset_id: 'earas_2023_24_district_minor_crops',
    label: 'EARAS district minor crops',
    years: '2023-24',
    grain: 'district × crop × season',
    row_count: 1170,
  },
  {
    dataset_id: 'earas_state_series',
    label: 'EARAS long-run state series',
    years: '1993-94 to 2024-25',
    grain: 'state × crop × season',
    row_count: 5632,
  },
];

export const MOCK_COLUMNS: SandboxColumn[] = [
  { name: 'district_id', label: 'District', dtype: 'categorical', role: 'feature' },
  { name: 'crop_id', label: 'Crop', dtype: 'categorical', role: 'feature' },
  { name: 'season', label: 'Season', dtype: 'categorical', role: 'feature' },
  { name: 'area_ha', label: 'Area sown (ha)', dtype: 'numeric', role: 'feature' },
  { name: 'yield_qtl_ha', label: 'Yield (qtl/ha)', dtype: 'numeric', role: 'target' },
  { name: 'production_qtl', label: 'Production (qtl)', dtype: 'numeric', role: 'both' },
  { name: 'agri_year', label: 'Agricultural year', dtype: 'categorical', role: 'identifier' },
];

const PER_CROP: PerCropMetric[] = [
  { crop_id: 'CR13', crop_name: 'Mung', r2: 0.412, rmse: 0.78, mae: 0.61, n: 90 },
  { crop_id: 'CR03', crop_name: 'Biri', r2: 0.447, rmse: 0.83, mae: 0.66, n: 90 },
  { crop_id: 'CR10', crop_name: 'Kulthi', r2: 0.388, rmse: 0.71, mae: 0.55, n: 84 },
  { crop_id: 'CR07', crop_name: 'Groundnut', r2: 0.596, rmse: 2.14, mae: 1.68, n: 78 },
  { crop_id: 'CR19', crop_name: 'Ragi', r2: 0.521, rmse: 1.42, mae: 1.11, n: 72 },
  { crop_id: 'CR22', crop_name: 'Til', r2: 0.334, rmse: 0.69, mae: 0.54, n: 66 },
  { crop_id: 'CR06', crop_name: 'Gram', r2: 0.409, rmse: 0.92, mae: 0.72, n: 60 },
  { crop_id: 'CR14', crop_name: 'Mustard', r2: 0.463, rmse: 1.06, mae: 0.83, n: 54 },
];

const ACTUAL_VS_PREDICTED: ActualVsPredicted[] = [
  { district_name: 'Bargarh', crop_name: 'Mung', actual: 5.42, predicted: 5.18, residual: 0.24 },
  { district_name: 'Balangir', crop_name: 'Mung', actual: 4.86, predicted: 5.03, residual: -0.17 },
  { district_name: 'Kalahandi', crop_name: 'Mung', actual: 5.91, predicted: 5.64, residual: 0.27 },
  { district_name: 'Nuapada', crop_name: 'Mung', actual: 4.38, predicted: 4.81, residual: -0.43 },
  { district_name: 'Cuttack', crop_name: 'Biri', actual: 6.34, predicted: 6.11, residual: 0.23 },
  { district_name: 'Balasore', crop_name: 'Biri', actual: 6.72, predicted: 6.48, residual: 0.24 },
  { district_name: 'Jajpur', crop_name: 'Biri', actual: 5.98, predicted: 6.22, residual: -0.24 },
  { district_name: 'Kendrapara', crop_name: 'Biri', actual: 6.41, predicted: 6.05, residual: 0.36 },
  { district_name: 'Ganjam', crop_name: 'Groundnut', actual: 16.84, predicted: 16.12, residual: 0.72 },
  { district_name: 'Puri', crop_name: 'Groundnut', actual: 15.47, predicted: 15.93, residual: -0.46 },
  { district_name: 'Gajapati', crop_name: 'Groundnut', actual: 14.22, predicted: 14.86, residual: -0.64 },
  { district_name: 'Kandhamal', crop_name: 'Ragi', actual: 11.38, predicted: 10.94, residual: 0.44 },
  { district_name: 'Koraput', crop_name: 'Ragi', actual: 12.06, predicted: 11.71, residual: 0.35 },
  { district_name: 'Nabarangpur', crop_name: 'Ragi', actual: 10.85, predicted: 11.28, residual: -0.43 },
  { district_name: 'Sundargarh', crop_name: 'Kulthi', actual: 5.73, predicted: 5.51, residual: 0.22 },
  { district_name: 'Keonjhar', crop_name: 'Kulthi', actual: 6.14, predicted: 5.87, residual: 0.27 },
  { district_name: 'Mayurbhanj', crop_name: 'Til', actual: 4.31, predicted: 4.55, residual: -0.24 },
  { district_name: 'Bhadrak', crop_name: 'Til', actual: 4.68, predicted: 4.42, residual: 0.26 },
  { district_name: 'Angul', crop_name: 'Gram', actual: 7.12, predicted: 6.84, residual: 0.28 },
  { district_name: 'Dhenkanal', crop_name: 'Mustard', actual: 6.58, predicted: 6.91, residual: -0.33 },
];

const FEATURE_IMPORTANCE: FeatureImportance[] = [
  { feature: 'crop_id', label: 'Crop', weight: 0.523 },
  { feature: 'district_id', label: 'District', weight: 0.244 },
  { feature: 'area_ha', label: 'Area sown', weight: 0.152 },
  { feature: 'season', label: 'Season', weight: 0.081 },
];

const PREDICTIONS: PredictionRow[] = [
  pred('OD04', 'Bargarh', 'CR13', 'Mung', 'Summer', 12480, 5.18),
  pred('OD02', 'Balangir', 'CR13', 'Mung', 'Summer', 10360, 5.03),
  pred('OD15', 'Kalahandi', 'CR13', 'Mung', 'Summer', 14210, 5.64),
  pred('OD25', 'Nuapada', 'CR13', 'Mung', 'Summer', 6840, 4.81),
  pred('OD07', 'Cuttack', 'CR03', 'Biri', 'Winter', 18720, 6.11),
  pred('OD03', 'Balasore', 'CR03', 'Biri', 'Winter', 21340, 6.48),
  pred('OD13', 'Jajpur', 'CR03', 'Biri', 'Winter', 15980, 6.22),
  pred('OD11', 'Ganjam', 'CR07', 'Groundnut', 'Summer', 28640, 16.12),
  pred('OD26', 'Puri', 'CR07', 'Groundnut', 'Summer', 19250, 15.93),
  pred('OD16', 'Kandhamal', 'CR19', 'Ragi', 'Winter', 24180, 10.94),
  pred('OD20', 'Koraput', 'CR19', 'Ragi', 'Winter', 31450, 11.71),
  pred('OD30', 'Sundargarh', 'CR10', 'Kulthi', 'Winter', 9720, 5.51),
  pred('OD22', 'Mayurbhanj', 'CR22', 'Til', 'Summer', 13560, 4.55),
  pred('OD01', 'Angul', 'CR06', 'Gram', 'Winter', 7480, 6.84),
];

function pred(
  district_id: string,
  district_name: string,
  crop_id: string,
  crop_name: string,
  season: string,
  area_ha: number,
  predicted_yield_qtl_per_ha: number,
): PredictionRow {
  return {
    district_id,
    district_name,
    crop_id,
    crop_name,
    season,
    area_ha,
    predicted_yield_qtl_per_ha,
    estimated_production_qtls: Math.round(area_ha * predicted_yield_qtl_per_ha),
    output_label: 'Analytical Estimates',
  };
}

const RESULTS: SandboxResults = {
  run_id: 'run-2024-25-minor-yield-07',
  pooled: { r2: 0.661, rmse: 1.84, mae: 1.12, n: 594 },
  per_crop: PER_CROP,
  actual_vs_predicted: ACTUAL_VS_PREDICTED,
  feature_importance: FEATURE_IMPORTANCE,
  explanation:
    'Crop identity carries most of the signal: minor crops occupy different yield ' +
    'bands, so knowing which crop is being grown explains more than half of the ' +
    'variance on its own. District contributes a further quarter, reflecting soil ' +
    'and rainfall differences across western and coastal Odisha. Sown area matters ' +
    'least and its relationship is weak, which is expected when the model is fitted ' +
    'on a single year with no time dimension. The pooled R² of 0.661 is therefore ' +
    'flattered by between-crop separation; the per-crop figures, which range from ' +
    '0.334 to 0.596, describe how well the model does within a crop.',
  predictions: PREDICTIONS,
  data_origin: { model: PREDICTIONS.length },
  served_from_cache: false,
};

/** The run progresses through these on successive status polls. */
const RUN_SEQUENCE: SandboxRunStatus[] = [
  { run_id: RESULTS.run_id, status: 'queued', progress: 0, message: 'Run queued.' },
  {
    run_id: RESULTS.run_id,
    status: 'running',
    progress: 18,
    message: 'Validating districts, crops and seasons against model metadata.',
  },
  {
    run_id: RESULTS.run_id,
    status: 'running',
    progress: 46,
    message: 'Requesting predictions for 594 district-crop-season combinations.',
  },
  {
    run_id: RESULTS.run_id,
    status: 'running',
    progress: 78,
    message: 'Scoring held-out records and computing residuals.',
  },
  {
    run_id: RESULTS.run_id,
    status: 'running',
    progress: 94,
    message: 'Ranking feature importance.',
  },
  { run_id: RESULTS.run_id, status: 'completed', progress: 100, message: 'Run complete.' },
];

export function mockUseCases(): Promise<SandboxUseCase[]> {
  return mockDelay(MOCK_USE_CASES, 200);
}

export function mockSandboxDatasets(): Promise<SandboxDataset[]> {
  return mockDelay(MOCK_DATASETS, 200);
}

export function mockSandboxColumns(): Promise<SandboxColumn[]> {
  return mockDelay(MOCK_COLUMNS, 220);
}

export function mockCreateRun(): Promise<{ run_id: string }> {
  return mockDelay({ run_id: RESULTS.run_id }, 260);
}

/** Step `index` of the run lifecycle; the page polls with an incrementing index. */
export function mockRunStatus(index: number): Promise<SandboxRunStatus> {
  const clamped = Math.min(index, RUN_SEQUENCE.length - 1);
  return mockDelay(RUN_SEQUENCE[clamped], 420);
}

export const RUN_STEP_COUNT = RUN_SEQUENCE.length;

export function mockRunResults(): Promise<SandboxResults> {
  return mockDelay(RESULTS, 460);
}

export function mockSaveVersion(runId: string, label: string): Promise<SandboxVersion> {
  return mockDelay(
    {
      version_id: 'ver-2024-25-minor-yield-03',
      run_id: runId,
      label,
      created_at: '2026-09-18T09:32:00',
      published: false,
      parameters: {
        use_case: 'Minor-crop yield estimation',
        dataset: 'earas_2024_25_district_crop_ayp',
        target: 'yield_qtl_ha',
        features: 'district_id, crop_id, season, area_ha',
        split: '80 / 20',
        horizon: 'Same-season estimate (no time dimension)',
      },
    },
    340,
  );
}

export function mockPublishVersion(versionId: string): Promise<{ version_id: string; published: true }> {
  return mockDelay({ version_id: versionId, published: true }, 380);
}
