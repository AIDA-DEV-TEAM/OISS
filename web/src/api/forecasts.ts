/**
 * Adapter: published model forecasts for the dashboard panel.
 *
 * Mocked until task 7 builds GET /dashboard/forecasts. To make it real, drop
 * the USE_MOCKS branch and call `api` — nothing in the panel changes.
 */
import { useQuery } from '@tanstack/react-query';

import type { PublishedForecast } from '@/api/contracts';
import { USE_MOCKS } from '@/mocks/config';
import { mockDashboardForecasts } from '@/mocks/forecasts';

export function fetchDashboardForecasts(): Promise<PublishedForecast[]> {
  if (USE_MOCKS) return mockDashboardForecasts();
  // Real call lands here: request<Page<PublishedForecast>>('/dashboard/forecasts')
  throw new Error('GET /dashboard/forecasts is not implemented yet (task 7).');
}

export function useDashboardForecasts() {
  return useQuery({
    queryKey: ['dashboard-forecasts'],
    queryFn: fetchDashboardForecasts,
  });
}
