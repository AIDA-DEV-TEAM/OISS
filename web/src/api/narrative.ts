/**
 * Adapter: grounded dashboard narrative (RFP area 4).
 *
 * Mocked until task 6 builds POST /narrative/dashboard. The fact bundle behind
 * it, POST /query/narrative-facts, is real today — task 6 hands that bundle to
 * the model and post-validates every number in the prose against it.
 */
import { useQuery } from '@tanstack/react-query';

import type { DashboardNarrative } from '@/api/contracts';
import { USE_MOCKS } from '@/mocks/config';
import { mockDashboardNarrative } from '@/mocks/narrative';

export type NarrativeView = 'price' | 'agriculture';

export function fetchDashboardNarrative(view: NarrativeView): Promise<DashboardNarrative> {
  if (USE_MOCKS) return mockDashboardNarrative(view);
  throw new Error('POST /narrative/dashboard is not implemented yet (task 6).');
}

export function useDashboardNarrative(view: NarrativeView) {
  return useQuery({
    queryKey: ['dashboard-narrative', view],
    queryFn: () => fetchDashboardNarrative(view),
  });
}
