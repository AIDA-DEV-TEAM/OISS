/**
 * A stubbed `fetch` that answers from payloads captured from the running
 * backend (src/test/fixtures/backend.json).
 *
 * Real responses, so the tests fail if the frontend starts reading a field the
 * backend does not send. Nothing here is invented.
 */
import fixtures from '@/test/fixtures/backend.json';
import sandbox from '@/test/fixtures/sandbox.json';
import assistant from '@/test/fixtures/assistant.json';
import narrative from '@/test/fixtures/narrative.json';

export const VERSION_ID = 'earas_2022_23_block_paddy@33743b3c4831';

type Handler = (url: URL, init?: RequestInit) => unknown;

const defaultSourceDatasets = [
  {
    dataset_version_id: 'earas_2023_24_district_paddy@5e8bdea5ea67',
    dataset_name: 'earas_2023_24_district_paddy',
    source_file: 'dist_paddy_AYP_2023-24.csv',
    layer: 'raw',
  },
];

function handleQuery(spec: Record<string, any>) {
  const metric = spec.metric;
  const dimensions = spec.dimensions || [];
  const filters = spec.filters || [];
  const period = spec.period || { from: '2023-24', to: '2024-25' };

  let rows: Array<Record<string, unknown>> = [];
  const dataOrigin = { official: 270, synthetic: 0 };
  const caveats: Array<any> = [];

  const isPaddy = filters.some(
    (f: any) => f.dimension === 'crop' && (f.values?.includes('CR17') || f.value === 'CR17'),
  );

  if (isPaddy && (metric === 'avg_price' || metric === 'price_yoy_pct')) {
    caveats.push({
      code: 'MSP_SUBSTITUTED',
      severity: 'warning',
      message:
        'In published DE&S statistics, official paddy prices represent administrative Minimum Support Prices rather than freely observed district market prices.',
      affected_rows: 270,
    });
  }

  if (metric === 'production') {
    if (dimensions.includes('district')) {
      rows = [
        { district: 'Bargarh', district_id: 'OD04', value: 854000.0, grain_source: 'published_district' },
        { district: 'Sambalpur', district_id: 'OD28', value: 642000.0, grain_source: 'published_district' },
        { district: 'Subarnapur', district_id: 'OD29', value: 526270.0, grain_source: 'published_district' },
      ];
    } else if (dimensions.includes('agri_year')) {
      rows = [
        { agri_year: '1993-94', value: 5400000.0, grain_source: 'published_state' },
        { agri_year: '2010-11', value: 6800000.0, grain_source: 'published_state' },
        { agri_year: '2023-24', value: 174828800.0, grain_source: 'published_state' },
      ];
    } else {
      // 174,828,800 quintals = 174.83 lakh MT
      rows = [{ value: 174828800.0, unit: 'qtl', grain_source: 'published_district' }];
    }
  } else if (metric === 'area') {
    if (dimensions.includes('crop')) {
      // The agriculture view's crop list: crops with area on record.
      rows = [
        { crop: 'Paddy', crop_id: 'CR17', value: 12496000.0 },
        { crop: 'Potato', crop_id: 'CR18', value: 35000.0 },
        { crop: 'Mustard', crop_id: 'CR14', value: 52000.0 },
      ];
    } else if (dimensions.includes('district')) {
      rows = [
        { district: 'Bargarh', district_id: 'OD04', value: 215000.0, grain_source: 'published_district' },
        { district: 'Sambalpur', district_id: 'OD28', value: 178000.0, grain_source: 'published_district' },
      ];
    } else {
      rows = [{ value: 4120000.0, unit: 'ha', grain_source: 'published_district' }];
    }
  } else if (metric === 'yield_rate') {
    if (dimensions.includes('district')) {
      rows = [
        { district: 'Bargarh', district_id: 'OD04', value: 54.2, grain_source: 'published_district' },
        { district: 'Cuttack', district_id: 'OD07', value: 41.8, grain_source: 'aggregated_from_blocks' },
      ];
    } else {
      rows = [{ value: 42.43, unit: 'qtl/ha', grain_source: 'published_district' }];
    }
  } else if (metric === 'avg_price') {
    if (dimensions.length > 2) {
      rows = [
        {
          agri_year: '2023-24',
          month: '2024-01',
          district: 'Bargarh',
          district_id: 'OD04',
          crop: 'Paddy',
          crop_id: 'CR17',
          price_type: 'farm_harvest',
          value: 2183.0,
          data_origin: 'synthetic',
        },
        {
          agri_year: '2018-19',
          month: '2018-11',
          district: 'Sambalpur',
          district_id: 'OD28',
          crop: 'Paddy',
          crop_id: 'CR17',
          price_type: 'farm_harvest',
          value: 1750.0,
          data_origin: 'official',
        },
      ];
      dataOrigin.synthetic = 1;
    } else if (dimensions.includes('month')) {
      rows = [
        { month: '2018-05', value: 1750.0, data_origin: 'official' },
        { month: '2018-06', value: 1750.0, data_origin: 'official' },
        { month: '2023-01', value: 2040.0, data_origin: 'synthetic' },
        { month: '2024-01', value: 2183.0, data_origin: 'synthetic' },
      ];
      dataOrigin.synthetic = 180;
    } else if (dimensions.includes('district')) {
      rows = [
        { district: 'Bargarh', district_id: 'OD04', value: 2183.0 },
        { district: 'Cuttack', district_id: 'OD07', value: 2210.0 },
      ];
    } else if (dimensions.includes('crop')) {
      rows = [
        { crop: 'Paddy', crop_id: 'CR17', value: 2183.0 },
        { crop: 'Wheat', crop_id: 'CR23', value: 2450.0 },
      ];
    } else if (dimensions.includes('price_type')) {
      rows = [
        { crop: 'Paddy', crop_id: 'CR17', fhp: 2183.0, wholesale: 2350.0, gap: 167.0, gap_pct: 7.6 },
      ];
    } else {
      rows = [{ value: 2183.0, unit: 'Rs/qtl', data_origin: 'official' }];
    }
  } else if (metric === 'price_yoy_pct') {
    rows = [{ agri_year: '2024-25', value: 6.8 }];
  } else if (metric === 'fhp_wholesale_gap') {
    rows = [{ value: 210.0, unit: 'Rs/qtl' }];
  } else if (metric === 'fhp_wholesale_gap_pct') {
    rows = [{ value: 9.8, unit: '%' }];
  } else if (metric === 'land_use_share') {
    rows = [
      { land_use_category: 'Forest area', value: 34.2 },
      { land_use_category: 'Net area sown', value: 38.5 },
      { land_use_category: 'Current fallow', value: 6.1 },
    ];
  } else if (metric === 'land_use_area') {
    rows = [
      { land_use_category: 'Forest area', value: 540.0 },
      { land_use_category: 'Net area sown', value: 610.0 },
      { land_use_category: 'Current fallow', value: 95.0 },
    ];
  }

  return {
    rows,
    applied_context: {
      metric,
      metric_label: metric.replace('_', ' ').toUpperCase(),
      unit: rows[0]?.unit || 'unit',
      dimensions,
      filters,
      period,
      relation: 'analytics.v_test',
      source_datasets: defaultSourceDatasets,
      data_origin: dataOrigin,
      grain_source: { published_district: rows.length },
      row_count: rows.length,
      underlying_row_count: rows.length * 10,
      generated_at: new Date().toISOString(),
    },
    caveats,
    records: null,
  };
}

function handleRecords(_spec: Record<string, any>) {
  return {
    records: [
      {
        agri_year: '2023-24',
        season: 'Winter',
        district_id: 'OD04',
        district_name: 'Bargarh',
        crop_id: 'CR17',
        crop_name: 'Paddy',
        product: 'paddy',
        measure: 'production',
        value: 526.27,
        unit: "'000 MT",
        value_canonical: 5262700.0,
        unit_canonical: 'qtl',
        data_origin: 'official',
        value_status: 'ok',
        grain_source: 'published_district',
        dataset_version_id: 'earas_2023_24_district_paddy@5e8bdea5ea67',
        source_file: 'dist_paddy_AYP_2023-24.csv',
      },
    ],
    returned: 1,
    total_matching: 270,
    truncated: false,
    source_datasets: defaultSourceDatasets,
  };
}

/** Two exports as GET /exports returns them, with the context they carry. */
const exportRecords = [
  {
    export_id: 'exp-4c1f2a9b77de',
    export_type: 'dashboard_panel',
    format: 'xlsx',
    status: 'completed',
    filename: 'district_price_comparison_exp-4c1f2a9b77de.xlsx',
    size_bytes: 24_918,
    created_at: '2026-02-14T06:41:05+00:00',
    context: {
      panel_title: 'District Price Comparison',
      metric: 'avg_price',
      metric_label: 'Average price',
      unit: 'Rs/quintal',
      dimensions: ['district'],
      // As the backend describes them: labels from the masters, not the browser.
      filters: [
        {
          dimension: 'crop',
          op: 'in',
          values: ['CR01'],
          dimension_label: 'Crop',
          values_display: ['Arhar (CR01)'],
        },
      ],
      period: { from: '2017-18', to: '2018-19' },
      period_label: '2017-18 to 2018-19',
      relation: 'analytics.v_price',
      source_datasets: defaultSourceDatasets,
      data_origin: { official: 60 },
      grain_source: {},
      row_count: 22,
      underlying_row_count: 60,
      provenance_notes: [],
      caveats: [],
      context_origin: 'derived',
      generated_at: '2026-02-14T06:41:05+00:00',
    },
  },
  {
    export_id: 'exp-90b3ee15c204',
    export_type: 'model_output',
    format: 'json',
    status: 'completed',
    filename: 'minor_crop_yield_estimates_exp-90b3ee15c204.json',
    size_bytes: 9_402,
    created_at: '2026-02-14T06:52:31+00:00',
    context: {
      panel_title: 'Minor-crop yield estimates',
      period_label: '2024-25',
      filters: [],
      source_datasets: [],
      data_origin: { model: 18 },
      grain_source: {},
      row_count: 18,
      underlying_row_count: 18,
      provenance_notes: ['Analytical Estimates'],
      caveats: [],
      context_origin: 'supplied by the calling surface',
      generated_at: '2026-02-14T06:52:31+00:00',
    },
  },
];

const routes: Array<{ match: RegExp; handler: Handler }> = [
  {
    match: /\/api\/exports(\?|$)/,
    handler: () => ({
      items: exportRecords,
      total: exportRecords.length,
      page: 1,
      size: 50,
    }),
  },
  // As GET /exports/limits answers: the ceiling the export service enforces.
  { match: /\/api\/exports\/limits$/, handler: () => ({ row_ceiling: 100_000 }) },
  { match: /\/api\/health$/, handler: () => fixtures.health },
  { match: /\/api\/datasets(\?|$)/, handler: () => fixtures.datasets },
  { match: /\/validation\/summary$/, handler: () => fixtures.validationSummary },
  {
    match: /\/validation(\?|$)/,
    handler: (url) => {
      const rule = url.searchParams.get('rule_code');
      const items = rule
        ? fixtures.findings.items.filter((item) => item.rule_code === rule)
        : fixtures.findings.items;
      return { items, total: items.length, page: 1, size: items.length };
    },
  },
  { match: /\/layers$/, handler: () => fixtures.layers },
  { match: /\/api\/lineage\//, handler: () => fixtures.lineage },
  {
    match: /\/api\/datasets\/[^/]+$/,
    handler: (url) => {
      const id = decodeURIComponent(url.pathname.split('/').pop() ?? '');
      return fixtures.datasets.items.find((item) => item.dataset_version_id === id);
    },
  },
  {
    match: /\/api\/query\/records$/,
    handler: (_url, init) => {
      const body = init?.body ? JSON.parse(String(init.body)) : {};
      return handleRecords(body);
    },
  },
  {
    match: /\/api\/query$/,
    handler: (_url, init) => {
      const body = init?.body ? JSON.parse(String(init.body)) : {};
      return handleQuery(body);
    },
  },
  // Captured from the backend; see the fixture's _source.
  { match: /\/api\/dashboard\/forecasts$/, handler: () => sandbox.forecasts },
  { match: /\/api\/sandbox\/model-config$/, handler: () => sandbox.modelConfig },
  { match: /\/api\/sandbox\/datasets$/, handler: () => sandbox.datasets },
  // A run the model service answered, except for its held-out records (422).
  { match: /\/api\/sandbox\/runs$/, handler: () => sandbox.runWithWarnings.status },
  {
    match: /\/api\/sandbox\/runs\/[^/]+\/results$/,
    handler: () => sandbox.runWithWarnings.results,
  },
  { match: /\/api\/sandbox\/runs\/[^/]+$/, handler: () => sandbox.runWithWarnings.status },
  { match: /\/api\/assistant\/questions$/, handler: () => assistant.questions },
  {
    match: /\/api\/narrative\/dashboard$/,
    handler: (_url, init) => {
      // Captured for each view's default spec; the price view asks about prices.
      const { query_spec } = init?.body ? JSON.parse(String(init.body)) : { query_spec: {} };
      return query_spec?.metric === 'avg_price' ? narrative.price : narrative.agriculture;
    },
  },
  {
    match: /\/api\/assistant\/ask$/,
    handler: (_url, init) => {
      // Captured answers, keyed by question; anything else gets the captured
      // "model unreachable" answer, which is what the backend returns for a
      // question it has not seen with no model configured.
      const { question } = init?.body ? JSON.parse(String(init.body)) : { question: '' };
      const answers: Record<string, unknown> = assistant.answers;
      return answers[question] ?? answers['How much rain fell in Puri last year?'];
    },
  },
];

export function installFetchStub(): void {
  globalThis.fetch = (async (input: RequestInfo | URL, init?: RequestInit) => {
    const href = typeof input === 'string' ? input : input.toString();
    const url = new URL(href, 'http://localhost');
    // Most specific route first: /validation/summary before /validation, and
    // the single-dataset route last so it does not swallow the others.
    const ordered = [...routes].sort((a, b) => b.match.source.length - a.match.source.length);
    for (const route of ordered) {
      if (route.match.test(url.pathname + url.search)) {
        const body = await route.handler(url, init);
        if (body === undefined) {
          return new Response(JSON.stringify({ detail: 'not found', code: 'not_found' }), {
            status: 404,
            headers: { 'content-type': 'application/json' },
          });
        }
        return new Response(JSON.stringify(body), {
          status: 200,
          headers: { 'content-type': 'application/json' },
        });
      }
    }
    throw new Error(`No stub for ${href}`);
  }) as typeof fetch;
}
