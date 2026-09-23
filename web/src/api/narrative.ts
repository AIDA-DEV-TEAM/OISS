/**
 * Adapter: dashboard narrative (RFP area 4). Real, as of task 6.
 *
 * The backend computes the view's facts in SQL and has the model describe
 * them, checking every number it writes against those facts. With no model
 * available it states the same facts from a template, and says which wrote it.
 */
import { useQuery } from '@tanstack/react-query';

import type { DashboardNarrative, QuerySpec } from '@/api/client';
import { api } from '@/api/client';

export function fetchDashboardNarrative(spec: QuerySpec): Promise<DashboardNarrative> {
  return api.narrative(spec);
}

/** Keyed by the view's spec, so a filter change asks for a fresh narrative. */
export function useDashboardNarrative(spec: QuerySpec) {
  return useQuery({
    queryKey: ['dashboard-narrative', spec],
    queryFn: () => fetchDashboardNarrative(spec),
    staleTime: Infinity,
  });
}
