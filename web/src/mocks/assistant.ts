/**
 * Predefined assistant questions and their grounded answers (RFP area 5).
 *
 * Feeds: AssistantPage → question chips, answer cards.
 * Replace with: POST /assistant/ask (task 6).
 *
 * The six cover what prompt 6 asks a demo to show: a district comparison, a
 * trend, leading and lagging, farm-harvest versus wholesale, one that must
 * surface the MSP caveat, and one the assistant declines because the data does
 * not exist. The refusal is the important one — a system that declines
 * accurately reads as more trustworthy than one that always answers.
 */
import { mockDelay } from '@/mocks/config';
import type { AssistantAnswer } from '@/api/contracts';

const PRICE_SOURCES = [
  { dataset_name: 'price_statistics_2020', dataset_version_id: 'price_statistics_2020@7b601ba6d9' },
  {
    dataset_name: 'synthetic_monthly_prices',
    dataset_version_id: 'synthetic_monthly_prices@cbb63a20c8',
  },
];

const AYP_SOURCES = [
  {
    dataset_name: 'earas_2024_25_district_crop_ayp',
    dataset_version_id: 'earas_2024_25_district_crop_ayp@3087f1ec29',
  },
];

const MSP_CAVEAT = {
  code: 'MSP_SUBSTITUTED',
  severity: 'warning',
  message:
    'Paddy is published at the Minimum Support Price, not an observed market price.',
  affected_rows: 319,
};

const SYNTHETIC_CAVEAT = {
  code: 'SYNTHETIC_DATA',
  severity: 'info',
  message:
    'Monthly price rows after 2018-19 are modelled from the published annual series.',
  affected_rows: 90564,
};

export const MOCK_ASSISTANT_ANSWERS: AssistantAnswer[] = [
  {
    question_id: 'district-compare-paddy-yield',
    question: 'Which districts had the highest paddy yield in 2024-25?',
    status: 'answered',
    answer:
      'Bargarh recorded the highest winter paddy yield in 2024-25 at 52.14 quintals per ' +
      'hectare, followed by Sambalpur at 49.87 and Subarnapur at 48.32. The state yield ' +
      'rate for the same season is 42.27 quintals per hectare, computed as total ' +
      'production over total area rather than as an average of district yields.',
    chart_spec: {
      kind: 'bar',
      x_key: 'district',
      y_key: 'yield',
      unit: 'qtl/ha',
      series_label: 'Winter paddy yield, 2024-25',
      data: [
        { district: 'Bargarh', yield: 52.14 },
        { district: 'Sambalpur', yield: 49.87 },
        { district: 'Subarnapur', yield: 48.32 },
        { district: 'Balangir', yield: 46.55 },
        { district: 'Jharsuguda', yield: 45.21 },
        { district: 'Kalahandi', yield: 44.08 },
        { district: 'Nuapada', yield: 41.76 },
        { district: 'Malkangiri', yield: 33.42 },
      ],
    },
    applied_filters: [
      { dimension: 'crop', values: ['Paddy'] },
      { dimension: 'season', values: ['Winter'] },
      { dimension: 'agri_year', values: ['2024-25'] },
    ],
    source_datasets: AYP_SOURCES,
    period: '2024-25',
    records_preview: [
      { district: 'Bargarh', season: 'Winter', area_ha: 176420, production_qtl: 9198538, yield_qtl_ha: 52.14 },
      { district: 'Sambalpur', season: 'Winter', area_ha: 128340, production_qtl: 6400316, yield_qtl_ha: 49.87 },
      { district: 'Subarnapur', season: 'Winter', area_ha: 91250, production_qtl: 4409200, yield_qtl_ha: 48.32 },
      { district: 'Balangir', season: 'Winter', area_ha: 163870, production_qtl: 7628149, yield_qtl_ha: 46.55 },
      { district: 'Malkangiri', season: 'Winter', area_ha: 72480, production_qtl: 2422282, yield_qtl_ha: 33.42 },
    ],
    caveats: [],
    served_from_cache: true,
    data_origin: { official: 450 },
    grain_source: { published_district: 450 },
  },
  {
    question_id: 'trend-paddy-production',
    question: 'How has paddy production changed since 1993-94?',
    status: 'answered',
    answer:
      'State paddy production rose from 57.84 lakh tonnes in 1993-94 to 176.23 lakh ' +
      'tonnes in 2024-25. The series is not monotonic: production fell to 46.12 lakh ' +
      'tonnes in 2002-03 following drought, and again to 68.21 lakh tonnes in 2015-16. ' +
      'The last three years sit between 174 and 181 lakh tonnes.',
    chart_spec: {
      kind: 'line',
      x_key: 'year',
      y_key: 'production',
      unit: 'lakh MT',
      series_label: 'State paddy production',
      data: [
        { year: '1993-94', production: 57.84 },
        { year: '1997-98', production: 74.33 },
        { year: '2002-03', production: 46.12 },
        { year: '2007-08', production: 85.06 },
        { year: '2011-12', production: 96.14 },
        { year: '2015-16', production: 68.21 },
        { year: '2019-20', production: 118.42 },
        { year: '2022-23', production: 180.8 },
        { year: '2023-24', production: 174.83 },
        { year: '2024-25', production: 176.23 },
      ],
    },
    applied_filters: [
      { dimension: 'crop', values: ['Paddy'] },
      { dimension: 'agri_year', values: ['1993-94 … 2024-25'] },
    ],
    source_datasets: [
      { dataset_name: 'earas_state_series', dataset_version_id: 'earas_state_series@d35b8a76b2' },
    ],
    period: '1993-94 to 2024-25',
    records_preview: [
      { agri_year: '2024-25', measure: 'production', value: 176.23, unit: 'lakh MT' },
      { agri_year: '2023-24', measure: 'production', value: 174.83, unit: 'lakh MT' },
      { agri_year: '2022-23', measure: 'production', value: 180.8, unit: 'lakh MT' },
      { agri_year: '2021-22', measure: 'production', value: 129.46, unit: 'lakh MT' },
    ],
    caveats: [],
    served_from_cache: true,
    data_origin: { official: 5632 },
  },
  {
    question_id: 'leading-lagging-price',
    question: 'Which districts lead and lag on farm-harvest prices?',
    status: 'answered',
    answer:
      'Bargarh leads on average farm-harvest price at 2,341 rupees per quintal and ' +
      'Malkangiri lags at 1,962 rupees per quintal, a spread of 379 rupees. The state ' +
      'average across the selected districts is 2,183 rupees per quintal. Prices after ' +
      '2018-19 are modelled rather than published.',
    chart_spec: {
      kind: 'bar',
      x_key: 'district',
      y_key: 'price',
      unit: 'Rs/qtl',
      series_label: 'Average farm-harvest price, 2024-25',
      data: [
        { district: 'Bargarh', price: 2341 },
        { district: 'Sambalpur', price: 2298 },
        { district: 'Cuttack', price: 2246 },
        { district: 'Puri', price: 2201 },
        { district: 'Ganjam', price: 2154 },
        { district: 'Koraput', price: 2043 },
        { district: 'Malkangiri', price: 1962 },
      ],
    },
    applied_filters: [
      { dimension: 'crop', values: ['Paddy'] },
      { dimension: 'price_type', values: ['Farm harvest'] },
      { dimension: 'agri_year', values: ['2024-25'] },
    ],
    source_datasets: PRICE_SOURCES,
    period: '2024-25',
    records_preview: [
      { district: 'Bargarh', price_type: 'farm_harvest', price_rs_per_quintal: 2341 },
      { district: 'Sambalpur', price_type: 'farm_harvest', price_rs_per_quintal: 2298 },
      { district: 'Malkangiri', price_type: 'farm_harvest', price_rs_per_quintal: 1962 },
    ],
    caveats: [SYNTHETIC_CAVEAT],
    served_from_cache: true,
    data_origin: { official: 0, synthetic: 360 },
  },
  {
    question_id: 'fhp-wholesale-gap',
    question: 'What is the gap between farm-harvest and wholesale prices?',
    status: 'answered',
    answer:
      'Across the thirteen crops published with both series, the mean farm-harvest to ' +
      'wholesale gap is 318 rupees per quintal, or 14.6 per cent of the farm-harvest ' +
      'price. The gap is widest for potato at 486 rupees per quintal and narrowest for ' +
      'sugarcane at 92 rupees per quintal.',
    chart_spec: {
      kind: 'bar',
      x_key: 'crop',
      y_key: 'gap',
      unit: 'Rs/qtl',
      series_label: 'Farm-harvest to wholesale gap',
      data: [
        { crop: 'Potato', gap: 486 },
        { crop: 'Mustard', gap: 412 },
        { crop: 'Groundnut', gap: 388 },
        { crop: 'Biri', gap: 344 },
        { crop: 'Paddy', gap: 318 },
        { crop: 'Maize', gap: 271 },
        { crop: 'Ragi', gap: 198 },
        { crop: 'Sugarcane', gap: 92 },
      ],
    },
    applied_filters: [
      { dimension: 'price_type', values: ['Farm harvest', 'Wholesale'] },
      { dimension: 'agri_year', values: ['2024-25'] },
    ],
    source_datasets: PRICE_SOURCES,
    period: '2024-25',
    records_preview: [
      { crop: 'Potato', farm_harvest: 1820, wholesale: 2306, gap: 486 },
      { crop: 'Paddy', farm_harvest: 2183, wholesale: 2501, gap: 318 },
      { crop: 'Sugarcane', farm_harvest: 342, wholesale: 434, gap: 92 },
    ],
    caveats: [SYNTHETIC_CAVEAT],
    served_from_cache: true,
    data_origin: { official: 0, synthetic: 1560 },
  },
  {
    question_id: 'paddy-price-msp',
    question: 'What is the average price of paddy in Cuttack?',
    status: 'answered',
    answer:
      'The average farm-harvest price of paddy in Cuttack for 2024-25 is 2,246 rupees ' +
      'per quintal. This figure is the Minimum Support Price rather than an observed ' +
      'market price: the publication substitutes MSP for paddy, so it describes what ' +
      'procurement paid, not what the market discovered.',
    chart_spec: {
      kind: 'line',
      x_key: 'year',
      y_key: 'price',
      unit: 'Rs/qtl',
      series_label: 'Paddy farm-harvest price, Cuttack',
      data: [
        { year: '2019-20', price: 1815 },
        { year: '2020-21', price: 1868 },
        { year: '2021-22', price: 1940 },
        { year: '2022-23', price: 2040 },
        { year: '2023-24', price: 2143 },
        { year: '2024-25', price: 2246 },
      ],
    },
    applied_filters: [
      { dimension: 'district', values: ['Cuttack'] },
      { dimension: 'crop', values: ['Paddy'] },
      { dimension: 'price_type', values: ['Farm harvest'] },
    ],
    source_datasets: PRICE_SOURCES,
    period: '2019-20 to 2024-25',
    records_preview: [
      { agri_year: '2024-25', district: 'Cuttack', price_rs_per_quintal: 2246 },
      { agri_year: '2023-24', district: 'Cuttack', price_rs_per_quintal: 2143 },
      { agri_year: '2022-23', district: 'Cuttack', price_rs_per_quintal: 2040 },
    ],
    caveats: [MSP_CAVEAT, SYNTHETIC_CAVEAT],
    served_from_cache: true,
    data_origin: { official: 0, synthetic: 72 },
  },
  {
    question_id: 'block-level-prices-declined',
    question: 'What were block-level wholesale prices in Bargarh in 2023-24?',
    status: 'declined',
    answer:
      'This cannot be answered from the loaded data. Price statistics are published at ' +
      'district grain only, so there is no block-level price to report for Bargarh or ' +
      'any other district. Separately, official price data ends at 2018-19: the newest ' +
      'DE&S price report in the catalogue stops there, and rows after it are modelled ' +
      'rather than published.',
    limitation:
      'No block grain exists for fact_price, and no official price rows exist after 2018-19.',
    chart_spec: null,
    applied_filters: [],
    source_datasets: [],
    period: null,
    records_preview: [],
    caveats: [],
    served_from_cache: true,
    data_origin: {},
  },
];

export function mockAssistantAsk(questionId: string): Promise<AssistantAnswer> {
  const found = MOCK_ASSISTANT_ANSWERS.find((a) => a.question_id === questionId);
  if (!found) return Promise.reject(new Error(`No cached answer for "${questionId}".`));
  return mockDelay(found, 680);
}

export function mockAssistantQuestions(): Promise<
  Array<{ question_id: string; question: string }>
> {
  return mockDelay(
    MOCK_ASSISTANT_ANSWERS.map(({ question_id, question }) => ({ question_id, question })),
    180,
  );
}
