import { useCallback, useMemo } from 'react';
import { useSearchParams } from 'react-router-dom';

import { PADDY_CROP_ID } from './constants';

export type DashboardView = 'price' | 'agriculture';
export type PriceType = 'farm_harvest' | 'wholesale';
/** Which price series the price view reads. The two are never averaged together. */
export type PriceSeries = 'synthetic' | 'official';
export type StateSeriesMetric = 'production' | 'area' | 'yield_rate';

export interface DashboardFilters {
  view: DashboardView;
  from: string;
  to: string;
  districts: string[]; // empty means all 30 districts
  // One crop at a time: every panel describes the same crop, and no figure
  // blends two crops' prices or yields.
  crop: string;
  season: string; // e.g. 'Winter'; empty means all seasons
  priceType: PriceType;
  priceSeries: PriceSeries;
  landUseDistrict: string; // for the 9-fold district chart
  stateSeriesMetric: StateSeriesMetric;
}

export function useDashboardFilters() {
  const [searchParams, setSearchParams] = useSearchParams();

  const view = (searchParams.get('view') as DashboardView) || 'price';
  const defaultFrom = view === 'price' ? '2013-14' : '2022-23';

  const from = searchParams.get('from') || defaultFrom;
  const to = searchParams.get('to') || '2024-25';

  const districts = useMemo(() => {
    const raw = searchParams.get('districts');
    if (!raw) return [];
    return raw.split(',').filter(Boolean);
  }, [searchParams]);

  const crop = searchParams.get('crop') || PADDY_CROP_ID;
  const season = searchParams.get('season') || (view === 'agriculture' ? 'Winter' : '');
  const priceType = (searchParams.get('price_type') as PriceType) || 'farm_harvest';
  const priceSeries = (searchParams.get('series') as PriceSeries) || 'synthetic';
  const landUseDistrict = searchParams.get('lu_dist') || 'OD04'; // Bargarh
  const stateSeriesMetric = (searchParams.get('ss_metric') as StateSeriesMetric) || 'production';

  const filters: DashboardFilters = useMemo(
    () => ({
      view,
      from,
      to,
      districts,
      crop,
      season,
      priceType,
      priceSeries,
      landUseDistrict,
      stateSeriesMetric,
    }),
    [view, from, to, districts, crop, season, priceType, priceSeries, landUseDistrict, stateSeriesMetric],
  );

  const updateFilters = useCallback(
    (updates: Partial<DashboardFilters>) => {
      setSearchParams((prev) => {
        const next = new URLSearchParams(prev);

        if (updates.view !== undefined) {
          next.set('view', updates.view);
          if (updates.from === undefined && !prev.has('from')) {
            next.set('from', updates.view === 'price' ? '2013-14' : '2022-23');
          }
        }
        if (updates.from !== undefined) next.set('from', updates.from);
        if (updates.to !== undefined) next.set('to', updates.to);

        if (updates.districts !== undefined) {
          if (updates.districts.length === 0) {
            next.delete('districts');
          } else {
            next.set('districts', updates.districts.join(','));
          }
        }

        if (updates.crop !== undefined) {
          if (updates.crop === PADDY_CROP_ID) next.delete('crop');
          else next.set('crop', updates.crop);
        }

        if (updates.season !== undefined) {
          if (!updates.season) next.delete('season');
          else next.set('season', updates.season);
        }

        if (updates.priceType !== undefined) {
          if (updates.priceType === 'farm_harvest') next.delete('price_type');
          else next.set('price_type', updates.priceType);
        }

        if (updates.priceSeries !== undefined) {
          if (updates.priceSeries === 'synthetic') next.delete('series');
          else next.set('series', updates.priceSeries);
        }

        if (updates.landUseDistrict !== undefined) {
          if (updates.landUseDistrict === 'OD04') next.delete('lu_dist');
          else next.set('lu_dist', updates.landUseDistrict);
        }

        if (updates.stateSeriesMetric !== undefined) {
          if (updates.stateSeriesMetric === 'production') next.delete('ss_metric');
          else next.set('ss_metric', updates.stateSeriesMetric);
        }

        return next;
      });
    },
    [setSearchParams],
  );

  const resetFilters = useCallback(() => {
    setSearchParams(new URLSearchParams({ view }));
  }, [setSearchParams, view]);

  return { filters, updateFilters, resetFilters };
}
