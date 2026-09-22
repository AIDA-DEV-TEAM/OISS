import { useState } from 'react';

import {
  AGRI_YEARS,
  ALL_CROPS,
  ALL_DISTRICTS,
  PADDY_CROP_ID,
  PRICE_TYPES,
  SEASONS,
} from './constants';
import type { DashboardFilters } from './useDashboardFilters';

export interface DashboardFilterBarProps {
  filters: DashboardFilters;
  onUpdate: (updates: Partial<DashboardFilters>) => void;
  onReset: () => void;
}

export function DashboardFilterBar({ filters, onUpdate, onReset }: DashboardFilterBarProps) {
  const [districtMenuOpen, setDistrictMenuOpen] = useState(false);
  const [cropMenuOpen, setCropMenuOpen] = useState(false);
  const [districtSearch, setDistrictSearch] = useState('');
  const [cropSearch, setCropSearch] = useState('');

  const filteredDistricts = ALL_DISTRICTS.filter((d) =>
    d.name.toLowerCase().includes(districtSearch.toLowerCase()),
  );

  const filteredCrops = ALL_CROPS.filter((c) =>
    c.name.toLowerCase().includes(cropSearch.toLowerCase()),
  );

  const toggleDistrict = (id: string) => {
    const next = filters.districts.includes(id)
      ? filters.districts.filter((d) => d !== id)
      : [...filters.districts, id];
    onUpdate({ districts: next });
  };

  const toggleCrop = (id: string) => {
    const next = filters.crops.includes(id)
      ? filters.crops.filter((c) => c !== id)
      : [...filters.crops, id];
    // Keep at least one crop selected
    onUpdate({ crops: next.length > 0 ? next : [PADDY_CROP_ID] });
  };

  return (
    <div className="sticky top-0 z-30 flex flex-col gap-2.5 border-b border-line bg-surface px-gutter py-3 shadow-sm">
      {/* Top row: View Switcher and Presets */}
      <div className="flex flex-wrap items-center justify-between gap-3">
        {/* Primary / Secondary Dashboard Tabs */}
        <div className="inline-flex rounded border border-line bg-surface-alt p-0.5" role="tablist">
          <button
            type="button"
            role="tab"
            aria-selected={filters.view === 'price'}
            onClick={() => onUpdate({ view: 'price' })}
            className={`rounded px-3 py-1.5 text-body font-medium transition-colors ${
              filters.view === 'price'
                ? 'bg-primary text-white shadow-sm'
                : 'text-ink-muted hover:text-ink'
            }`}
          >
            Price Statistics
            <span className="ml-1.5 text-badge font-normal opacity-80">(Primary)</span>
          </button>
          <button
            type="button"
            role="tab"
            aria-selected={filters.view === 'agriculture'}
            onClick={() => onUpdate({ view: 'agriculture' })}
            className={`rounded px-3 py-1.5 text-body font-medium transition-colors ${
              filters.view === 'agriculture'
                ? 'bg-primary text-white shadow-sm'
                : 'text-ink-muted hover:text-ink'
            }`}
          >
            Agriculture / EARAS
            <span className="ml-1.5 text-badge font-normal opacity-80">(Secondary)</span>
          </button>
        </div>

        {/* Quick Presets */}
        <div className="flex items-center gap-2">
          <span className="text-caption font-medium uppercase tracking-header text-ink-subtle">
            Presets:
          </span>
          <button
            type="button"
            onClick={() => onUpdate({ from: '2023-24', to: '2024-25', crops: [PADDY_CROP_ID], districts: [] })}
            className="rounded border border-line bg-surface px-2.5 py-1 text-caption text-ink hover:bg-surface-alt"
          >
            Latest Paddy (All Districts)
          </button>
          <button
            type="button"
            onClick={() => onUpdate({ crops: [PADDY_CROP_ID] })}
            className="rounded border border-line bg-surface px-2.5 py-1 text-caption text-ink hover:bg-surface-alt"
          >
            Paddy Only
          </button>
          <button
            type="button"
            onClick={onReset}
            className="rounded border border-line px-2.5 py-1 text-caption text-ink-muted hover:bg-surface-alt hover:text-ink"
          >
            Reset Filters
          </button>
        </div>
      </div>

      {/* Bottom row: Active Filter Controls */}
      <div className="flex flex-wrap items-center gap-3">
        {/* Year From */}
        <div className="flex items-center gap-1.5">
          <label htmlFor="filter-from" className="text-caption font-medium uppercase tracking-header text-ink-subtle">
            From:
          </label>
          <select
            id="filter-from"
            value={filters.from}
            onChange={(e) => onUpdate({ from: e.target.value })}
            className="rounded border border-line bg-surface px-2.5 py-1.5 text-body font-normal text-ink focus:border-primary focus:outline-none"
          >
            {AGRI_YEARS.map((y) => (
              <option key={y} value={y}>
                {y}
              </option>
            ))}
          </select>
        </div>

        {/* Year To */}
        <div className="flex items-center gap-1.5">
          <label htmlFor="filter-to" className="text-caption font-medium uppercase tracking-header text-ink-subtle">
            To:
          </label>
          <select
            id="filter-to"
            value={filters.to}
            onChange={(e) => onUpdate({ to: e.target.value })}
            className="rounded border border-line bg-surface px-2.5 py-1.5 text-body font-normal text-ink focus:border-primary focus:outline-none"
          >
            {AGRI_YEARS.map((y) => (
              <option key={y} value={y}>
                {y}
              </option>
            ))}
          </select>
        </div>

        {/* District Multi-select Dropdown */}
        <div className="relative">
          <button
            type="button"
            onClick={() => {
              setDistrictMenuOpen(!districtMenuOpen);
              setCropMenuOpen(false);
            }}
            className="inline-flex items-center gap-1.5 rounded border border-line bg-surface px-3 py-1.5 text-body text-ink hover:border-line-strong focus:outline-none focus:ring-1 focus:ring-primary"
          >
            <span className="text-caption font-medium uppercase tracking-header text-ink-subtle">Districts:</span>
            <span className="font-medium">
              {filters.districts.length === 0
                ? 'All 30 districts'
                : `${filters.districts.length} selected`}
            </span>
            <span className="text-ink-muted">▼</span>
          </button>

          {districtMenuOpen && (
            <div className="absolute left-0 top-full z-40 mt-1 max-h-80 w-64 overflow-y-auto rounded-card border border-line bg-surface p-2 shadow-lg">
              <input
                type="text"
                placeholder="Filter districts..."
                value={districtSearch}
                onChange={(e) => setDistrictSearch(e.target.value)}
                className="mb-2 w-full rounded border border-line px-2 py-1 text-caption text-ink focus:outline-none focus:ring-1 focus:ring-primary"
              />
              <div className="mb-2 flex items-center justify-between border-b border-line pb-1.5 text-caption">
                <button
                  type="button"
                  onClick={() => onUpdate({ districts: [] })}
                  className="text-primary hover:underline"
                >
                  All (30)
                </button>
                <button
                  type="button"
                  onClick={() => onUpdate({ districts: [] })}
                  className="text-ink-muted hover:underline"
                >
                  Clear
                </button>
              </div>
              <div className="space-y-1">
                {filteredDistricts.map((d) => {
                  const checked = filters.districts.length === 0 || filters.districts.includes(d.id);
                  return (
                    <label
                      key={d.id}
                      className="flex cursor-pointer items-center gap-2 rounded px-1.5 py-1 text-body text-ink hover:bg-surface-alt"
                    >
                      <input
                        type="checkbox"
                        checked={checked}
                        onChange={() => toggleDistrict(d.id)}
                        className="rounded border-line text-primary focus:ring-primary"
                      />
                      <span>{d.name}</span>
                    </label>
                  );
                })}
              </div>
            </div>
          )}
        </div>

        {/* Crop Multi-select Dropdown */}
        <div className="relative">
          <button
            type="button"
            onClick={() => {
              setCropMenuOpen(!cropMenuOpen);
              setDistrictMenuOpen(false);
            }}
            className="inline-flex items-center gap-1.5 rounded border border-line bg-surface px-3 py-1.5 text-body text-ink hover:border-line-strong focus:outline-none focus:ring-1 focus:ring-primary"
          >
            <span className="text-caption font-medium uppercase tracking-header text-ink-subtle">Crops:</span>
            <span className="font-medium">
              {filters.crops.length === 1
                ? ALL_CROPS.find((c) => c.id === filters.crops[0])?.name || filters.crops[0]
                : `${filters.crops.length} selected`}
            </span>
            <span className="text-ink-muted">▼</span>
          </button>

          {cropMenuOpen && (
            <div className="absolute left-0 top-full z-40 mt-1 max-h-80 w-64 overflow-y-auto rounded-card border border-line bg-surface p-2 shadow-lg">
              <input
                type="text"
                placeholder="Filter crops..."
                value={cropSearch}
                onChange={(e) => setCropSearch(e.target.value)}
                className="mb-2 w-full rounded border border-line px-2 py-1 text-caption text-ink focus:outline-none focus:ring-1 focus:ring-primary"
              />
              <div className="mb-2 flex items-center justify-between border-b border-line pb-1.5 text-caption">
                <button
                  type="button"
                  onClick={() => onUpdate({ crops: [PADDY_CROP_ID] })}
                  className="text-primary hover:underline"
                >
                  Paddy only
                </button>
                <button
                  type="button"
                  onClick={() => onUpdate({ crops: ALL_CROPS.map((c) => c.id) })}
                  className="text-ink-muted hover:underline"
                >
                  Select all
                </button>
              </div>
              <div className="space-y-1">
                {filteredCrops.map((c) => {
                  const checked = filters.crops.includes(c.id);
                  return (
                    <label
                      key={c.id}
                      className="flex cursor-pointer items-center gap-2 rounded px-1.5 py-1 text-body text-ink hover:bg-surface-alt"
                    >
                      <input
                        type="checkbox"
                        checked={checked}
                        onChange={() => toggleCrop(c.id)}
                        className="rounded border-line text-primary focus:ring-primary"
                      />
                      <span>{c.name}</span>
                    </label>
                  );
                })}
              </div>
            </div>
          )}
        </div>

        {/* Season Selector */}
        <div className="flex items-center gap-1.5">
          <label htmlFor="filter-season" className="text-caption font-medium uppercase tracking-header text-ink-subtle">
            Season:
          </label>
          <select
            id="filter-season"
            value={filters.season}
            onChange={(e) => onUpdate({ season: e.target.value })}
            className="rounded border border-line bg-surface px-2.5 py-1.5 text-body font-normal text-ink focus:border-primary focus:outline-none"
          >
            <option value="">All seasons</option>
            {SEASONS.map((s) => (
              <option key={s} value={s}>
                {s}
              </option>
            ))}
          </select>
        </div>

        {/* Price Type (only relevant for Price view) */}
        {filters.view === 'price' && (
          <div className="flex items-center gap-1.5">
            <label htmlFor="filter-price-type" className="text-caption font-medium uppercase tracking-header text-ink-subtle">
              Price type:
            </label>
            <select
              id="filter-price-type"
              value={filters.priceType}
              onChange={(e) => onUpdate({ priceType: e.target.value as DashboardFilters['priceType'] })}
              className="rounded border border-line bg-surface px-2.5 py-1.5 text-body font-normal text-ink focus:border-primary focus:outline-none"
            >
              {PRICE_TYPES.map((pt) => (
                <option key={pt.id} value={pt.id}>
                  {pt.label}
                </option>
              ))}
            </select>
          </div>
        )}
      </div>
    </div>
  );
}
