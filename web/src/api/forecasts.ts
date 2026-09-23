/**
 * Adapter: published model forecasts for the dashboard panel.
 *
 * Real, wired to GET /dashboard/forecasts (Task 7).
 */
import { useQuery } from '@tanstack/react-query';

import { api } from '@/api/client';
import type { PublishedForecast } from '@/api/client';

export function fetchDashboardForecasts(): Promise<PublishedForecast[]> {
  return api.dashboardForecasts();
}

export function useDashboardForecasts() {
  return useQuery({
    queryKey: ['dashboard-forecasts'],
    queryFn: fetchDashboardForecasts,
  });
}

