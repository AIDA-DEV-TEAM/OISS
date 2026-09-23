import { useQuery } from '@tanstack/react-query';

import type { QuerySpec } from '@/api/client';
import { api } from '@/api/client';

export interface AvailableCrop {
  id: string;
  name: string;
}

interface AvailableCropsOptions {
  view: 'price' | 'agriculture';
  priceType: string;
  priceSeries: string;
}

/**
 * The crops the current view actually holds data for, asked of the data
 * rather than listed by hand. Area, production and yield exist for 14 crops;
 * wholesale prices for 13. Offering the rest would only lead to empty panels.
 */
export function availabilitySpec({ view, priceType, priceSeries }: AvailableCropsOptions): QuerySpec {
  return view === 'agriculture'
    ? { metric: 'area', dimensions: ['crop'], limit: 100, include_records: false }
    : {
        metric: 'avg_price',
        dimensions: ['crop'],
        filters: [
          { dimension: 'price_type', op: 'eq', values: [priceType] },
          { dimension: 'data_origin', op: 'eq', values: [priceSeries] },
        ],
        limit: 100,
        include_records: false,
      };
}

export function useAvailableCrops(options: AvailableCropsOptions) {
  const spec = availabilitySpec(options);
  return useQuery({
    queryKey: ['available-crops', spec],
    queryFn: () => api.query(spec),
    staleTime: Infinity,
    select: (response): AvailableCrop[] =>
      response.rows
        .filter((row) => typeof row.value === 'number' && row.value > 0)
        .map((row) => ({ id: String(row.crop_id), name: String(row.crop) }))
        .sort((a, b) => a.name.localeCompare(b.name)),
  });
}
