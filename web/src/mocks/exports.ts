/**
 * Export jobs and their carried context (RFP area 8).
 *
 * Feeds: ExportModal (create) and ExportsPage (recent list).
 * Replace with: POST /export, GET /export/{id}, GET /exports (task 5).
 *
 * Task 5's central rule is that an export carries its applied context, not just
 * rows. Every record here therefore holds the filters, period, row count,
 * source dataset versions, origin and grain mix, and caveats that produced it —
 * the same `ExportContext` the modal previews before the download starts.
 */
import { mockDelay } from '@/mocks/config';
import type {
  ExportContext,
  ExportFormat,
  ExportRecord,
  ExportType,
} from '@/api/contracts';

const PRICE_CONTEXT: ExportContext = {
  panel_title: 'District comparison — average farm-harvest price',
  filters: [
    { dimension: 'crop', values: ['Paddy'] },
    { dimension: 'price_type', values: ['Farm harvest'] },
    { dimension: 'agri_year', values: ['2024-25'] },
  ],
  period: '2024-25',
  row_count: 360,
  source_datasets: [
    { dataset_name: 'price_statistics_2020', dataset_version_id: 'price_statistics_2020@7b601ba6d9' },
    {
      dataset_name: 'synthetic_monthly_prices',
      dataset_version_id: 'synthetic_monthly_prices@cbb63a20c8',
    },
  ],
  data_origin: { official: 0, synthetic: 360 },
  caveats: [
    {
      code: 'MSP_SUBSTITUTED',
      severity: 'warning',
      message: 'Paddy is published at the Minimum Support Price, not an observed market price.',
      affected_rows: 319,
    },
    {
      code: 'SYNTHETIC_DATA',
      severity: 'info',
      message: 'Monthly price rows after 2018-19 are modelled from the published annual series.',
      affected_rows: 360,
    },
  ],
};

const AYP_CONTEXT: ExportContext = {
  panel_title: 'District paddy production, 2024-25',
  filters: [
    { dimension: 'crop', values: ['Paddy'] },
    { dimension: 'season', values: ['Winter'] },
    { dimension: 'agri_year', values: ['2024-25'] },
  ],
  period: '2024-25',
  row_count: 450,
  source_datasets: [
    {
      dataset_name: 'earas_2024_25_district_crop_ayp',
      dataset_version_id: 'earas_2024_25_district_crop_ayp@3087f1ec29',
    },
  ],
  data_origin: { official: 450 },
  grain_source: { published_district: 450 },
  caveats: [],
};

const STATE_SERIES_CONTEXT: ExportContext = {
  panel_title: 'Long-run state series, 1993-94 to 2024-25',
  filters: [{ dimension: 'crop', values: ['Paddy'] }],
  period: '1993-94 to 2024-25',
  row_count: 5632,
  source_datasets: [
    { dataset_name: 'earas_state_series', dataset_version_id: 'earas_state_series@d35b8a76b2' },
  ],
  data_origin: { official: 5632 },
  caveats: [],
};

const MODEL_CONTEXT: ExportContext = {
  panel_title: 'Minor-crop yield estimates — run 07',
  filters: [
    { dimension: 'crop', values: ['Mung', 'Biri', 'Groundnut', 'Ragi', 'Kulthi', 'Til', 'Gram'] },
    { dimension: 'agri_year', values: ['2024-25'] },
  ],
  period: '2024-25',
  row_count: 14,
  source_datasets: [
    {
      dataset_name: 'earas_2024_25_district_crop_ayp',
      dataset_version_id: 'earas_2024_25_district_crop_ayp@3087f1ec29',
    },
  ],
  data_origin: { model: 14 },
  caveats: [],
};

export const MOCK_EXPORTS: ExportRecord[] = [
  {
    export_id: 'exp-000147',
    export_type: 'dashboard_panel',
    format: 'xlsx',
    status: 'completed',
    filename: 'district_farm_harvest_price_2024-25.xlsx',
    size_bytes: 48213,
    created_at: '2026-09-18T09:28:14',
    context: PRICE_CONTEXT,
  },
  {
    export_id: 'exp-000146',
    export_type: 'records_grid',
    format: 'csv',
    status: 'completed',
    filename: 'district_paddy_production_2024-25.csv',
    size_bytes: 21874,
    created_at: '2026-09-18T09:19:02',
    context: AYP_CONTEXT,
  },
  {
    export_id: 'exp-000145',
    export_type: 'model_output',
    format: 'json',
    status: 'completed',
    filename: 'minor_crop_yield_run_07.json',
    size_bytes: 9432,
    created_at: '2026-09-18T08:57:41',
    context: MODEL_CONTEXT,
  },
  {
    export_id: 'exp-000144',
    export_type: 'dashboard_panel',
    format: 'png',
    status: 'completed',
    filename: 'state_paddy_series_1993-2025.png',
    size_bytes: 137608,
    created_at: '2026-09-18T08:44:19',
    context: STATE_SERIES_CONTEXT,
  },
  {
    export_id: 'exp-000143',
    export_type: 'narrative',
    format: 'pdf',
    status: 'completed',
    filename: 'agriculture_dashboard_summary.pdf',
    size_bytes: 264915,
    created_at: '2026-09-18T08:31:55',
    context: AYP_CONTEXT,
  },
  {
    export_id: 'exp-000142',
    export_type: 'assistant_answer',
    format: 'pdf',
    status: 'completed',
    filename: 'highest_paddy_yield_2024-25.pdf',
    size_bytes: 188340,
    created_at: '2026-09-18T08:12:07',
    context: AYP_CONTEXT,
  },
];

export function mockRecentExports(): Promise<ExportRecord[]> {
  return mockDelay(MOCK_EXPORTS, 300);
}

/** Mirrors POST /export followed by the job completing. */
export function mockCreateExport(input: {
  export_type: ExportType;
  format: ExportFormat;
  context: ExportContext;
}): Promise<ExportRecord> {
  const stamp = String(MOCK_EXPORTS.length + 142).padStart(6, '0');
  const slug = input.context.panel_title
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, '_')
    .replace(/^_+|_+$/g, '')
    .slice(0, 48);
  return mockDelay(
    {
      export_id: `exp-${stamp}`,
      export_type: input.export_type,
      format: input.format,
      status: 'completed',
      filename: `${slug}.${input.format}`,
      size_bytes: 12_000 + input.context.row_count * 37,
      created_at: new Date().toISOString().slice(0, 19),
      context: input.context,
    },
    900,
  );
}
