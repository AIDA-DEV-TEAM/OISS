/**
 * Grounded dashboard narrative for the GenAI explanation panel (RFP area 4).
 *
 * Feeds: PriceDashboard and AgricultureDashboard → NarrativePanel.
 * Replace with: POST /narrative/dashboard (task 6).
 *
 * Every number in `narrative` also appears in `facts_used`. That is the rule
 * task 6 enforces by post-validating model output against the fact bundle, and
 * holding to it here means the panel behaves the same before and after wiring.
 */
import { mockDelay } from '@/mocks/config';
import type { DashboardNarrative } from '@/api/contracts';

const PRICE_NARRATIVE: DashboardNarrative = {
  narrative:
    'Across the selected districts, the average farm-harvest price of paddy is ' +
    '2,183 rupees per quintal for 2024-25, 4.6 per cent above the previous year. ' +
    'Bargarh records the highest district average at 2,341 rupees per quintal and ' +
    'Malkangiri the lowest at 1,962 rupees per quintal, a spread of 379 rupees. ' +
    'The farm-harvest to wholesale gap stands at 318 rupees per quintal. Paddy is ' +
    'reported at the Minimum Support Price rather than an observed market price, ' +
    'so these figures describe the procurement regime, not price discovery. ' +
    'Monthly values after 2018-19 are modelled rather than published.',
  facts_used: [
    { label: 'Average farm-harvest price', value: 2183, unit: 'Rs/qtl', scope: 'Paddy, 2024-25' },
    { label: 'Year-on-year change', value: 4.6, unit: '%', scope: '2023-24 to 2024-25' },
    { label: 'Highest district average', value: 2341, unit: 'Rs/qtl', scope: 'Bargarh' },
    { label: 'Lowest district average', value: 1962, unit: 'Rs/qtl', scope: 'Malkangiri' },
    { label: 'Spread across districts', value: 379, unit: 'Rs/qtl', scope: '2024-25' },
    { label: 'Farm-harvest to wholesale gap', value: 318, unit: 'Rs/qtl', scope: 'Paddy, 2024-25' },
  ],
  caveats: [
    {
      code: 'MSP_SUBSTITUTED',
      severity: 'warning',
      message:
        'Paddy is published at the Minimum Support Price, not an observed market price. ' +
        'Treat these rows as the procurement price for the season.',
      affected_rows: 319,
    },
    {
      code: 'SYNTHETIC_DATA',
      severity: 'info',
      message:
        'Monthly price rows after 2018-19 are modelled from the published annual series. ' +
        'They are not DE&S statistics.',
      affected_rows: 90564,
    },
  ],
  served_from_cache: true,
  data_origin: { official: 6300, synthetic: 90564 },
};

const AGRICULTURE_NARRATIVE: DashboardNarrative = {
  narrative:
    'Paddy production for 2024-25 is 176.23 lakh tonnes from 41.69 lakh hectares, ' +
    'giving a state yield rate of 42.27 quintals per hectare. Production is 0.8 per ' +
    'cent above 2023-24, when the state recorded 174.83 lakh tonnes. Bargarh leads ' +
    'district production and Malkangiri trails it. Winter paddy accounts for the ' +
    'largest share of the season split at 34.48 lakh hectares. District figures for ' +
    '2022-23 are summed from block records because DE&S published that year at block ' +
    'grain only, and the yield for those rows is recomputed as total production over ' +
    'total area.',
  facts_used: [
    { label: 'Production', value: 176.23, unit: 'lakh MT', scope: 'Paddy, 2024-25' },
    { label: 'Area', value: 41.69, unit: 'lakh ha', scope: 'Paddy, 2024-25' },
    { label: 'State yield rate', value: 42.27, unit: 'qtl/ha', scope: 'Paddy, 2024-25' },
    { label: 'Year-on-year change', value: 0.8, unit: '%', scope: '2023-24 to 2024-25' },
    { label: 'Previous year production', value: 174.83, unit: 'lakh MT', scope: 'Paddy, 2023-24' },
    { label: 'Winter paddy area', value: 34.48, unit: 'lakh ha', scope: '2024-25' },
  ],
  caveats: [
    {
      code: 'AGGREGATED_FROM_BLOCKS',
      severity: 'info',
      message:
        'District paddy figures for 2022-23 are aggregated from block records. ' +
        'DE&S published that year block-wise only.',
      affected_rows: 270,
    },
  ],
  served_from_cache: true,
  data_origin: { official: 17952 },
  grain_source: { published_district: 11760, aggregated_from_blocks: 270 },
};

export function mockDashboardNarrative(view: 'price' | 'agriculture'): Promise<DashboardNarrative> {
  return mockDelay(view === 'price' ? PRICE_NARRATIVE : AGRICULTURE_NARRATIVE, 520);
}
