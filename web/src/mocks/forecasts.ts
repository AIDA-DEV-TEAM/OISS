/**
 * Published model forecasts for the dashboard's actual-vs-forecast panel.
 *
 * Feeds: AgricultureDashboard → ActualVsForecastPanel.
 * Replace with: GET /dashboard/forecasts (task 7).
 *
 * Values are minor-crop yields in qtl/ha at magnitudes EARAS actually reports
 * for Odisha — pulses in the 4–7 range, groundnut mid-teens, ragi around 11.
 * `actual_yield` is null where 2024-25 has not been published for that pairing;
 * the panel renders those as gaps, never as zero.
 */
import { mockDelay } from '@/mocks/config';
import type { PublishedForecast } from '@/api/contracts';

const MODEL_ORIGIN = { model: 1 };
const LABEL = 'Analytical Estimates';

function row(
  district_id: string,
  district_name: string,
  crop_id: string,
  crop_name: string,
  season: string,
  actual_yield: number | null,
  forecast_yield: number,
): PublishedForecast {
  return {
    district_id,
    district_name,
    crop_id,
    crop_name,
    season,
    agri_year: '2024-25',
    actual_yield,
    forecast_yield,
    unit: 'qtl/ha',
    version_id: 'ver-2024-25-minor-yield-03',
    output_label: LABEL,
    data_origin: MODEL_ORIGIN,
  };
}

export const MOCK_FORECASTS: PublishedForecast[] = [
  row('OD04', 'Bargarh', 'CR13', 'Mung', 'Summer', 5.42, 5.18),
  row('OD02', 'Balangir', 'CR13', 'Mung', 'Summer', 4.86, 5.03),
  row('OD15', 'Kalahandi', 'CR13', 'Mung', 'Summer', 5.91, 5.64),
  row('OD27', 'Rayagada', 'CR13', 'Mung', 'Summer', null, 4.72),
  row('OD07', 'Cuttack', 'CR03', 'Biri', 'Winter', 6.34, 6.11),
  row('OD03', 'Balasore', 'CR03', 'Biri', 'Winter', 6.72, 6.48),
  row('OD13', 'Jajpur', 'CR03', 'Biri', 'Winter', 5.98, 6.22),
  row('OD17', 'Kendrapara', 'CR03', 'Biri', 'Winter', null, 6.05),
  row('OD11', 'Ganjam', 'CR07', 'Groundnut', 'Summer', 16.84, 16.12),
  row('OD26', 'Puri', 'CR07', 'Groundnut', 'Summer', 15.47, 15.93),
  row('OD10', 'Gajapati', 'CR07', 'Groundnut', 'Summer', 14.22, 14.86),
  row('OD16', 'Kandhamal', 'CR19', 'Ragi', 'Winter', 11.38, 10.94),
  row('OD20', 'Koraput', 'CR19', 'Ragi', 'Winter', 12.06, 11.71),
  row('OD23', 'Nabarangpur', 'CR19', 'Ragi', 'Winter', 10.85, 11.28),
  row('OD30', 'Sundargarh', 'CR10', 'Kulthi', 'Winter', 5.73, 5.51),
  row('OD18', 'Keonjhar', 'CR10', 'Kulthi', 'Winter', 6.14, 5.87),
  row('OD22', 'Mayurbhanj', 'CR22', 'Til', 'Summer', 4.31, 4.55),
  row('OD05', 'Bhadrak', 'CR22', 'Til', 'Summer', 4.68, 4.42),
];

export function mockDashboardForecasts(): Promise<PublishedForecast[]> {
  return mockDelay(MOCK_FORECASTS);
}
