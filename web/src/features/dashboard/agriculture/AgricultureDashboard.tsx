import { useEffect, useMemo } from 'react';
import { useQuery } from '@tanstack/react-query';
import {
  Bar,
  BarChart,
  CartesianGrid,
  Cell,
  Legend,
  Line,
  LineChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from 'recharts';

import { api, type AppliedContext, type Caveat, type QuerySpec } from '@/api/client';
import { Card, Figure, StatCard } from '@/components/primitives';
import { EmptyState, ErrorState, LoadingState } from '@/components/states';
import { ActualVsForecastPanel } from '@/features/dashboard/ActualVsForecastPanel';
import { NarrativePanel } from '@/features/dashboard/NarrativePanel';
import {
  ALL_DISTRICTS,
  CHART_COLORS,
} from '../constants';
import { ExportButton } from '@/components/ExportButton';
import { contextFromApplied, cropDisplayName, toExportContext } from '@/lib/exportContext';
import type { PanelExport } from '@/lib/exportContext';
import type { DashboardFilters } from '../useDashboardFilters';

export interface AgricultureDashboardProps {
  filters: DashboardFilters;
  onDrillDown: (spec: QuerySpec, title: string) => void;
  onExport: (panel: PanelExport) => void;
  onUpdateFilters: (updates: Partial<DashboardFilters>) => void;
  onContextUpdate?: (context: AppliedContext, caveats: Caveat[]) => void;
}

const NOT_NINE_FOLD = new Set([
  'Geographical area',
  'Total area under survey',
  'Area not included under survey',
  'Net area sown (irrigated)',
  'Net area sown (unirrigated)',
]);

export function AgricultureDashboard({
  filters,
  onDrillDown,
  onExport,
  onUpdateFilters,
  onContextUpdate,
}: AgricultureDashboardProps) {
  const { from, to, districts, crop, season, landUseDistrict, stateSeriesMetric } = filters;
  const activeCrop = crop;
  const periodLabel = from === to ? from : `${from} to ${to}`;
  // What the KPIs sum over: the period, and the season when one is chosen.
  const sumScope = `${periodLabel}${season ? `, ${season} season` : ', all seasons'}`;

  // 1. KPI Queries
  /** One panel's export, carrying that panel's own query rather than the KPI's. */
  const panelExport = (
    title: string,
    spec: QuerySpec,
    result?: { applied_context: AppliedContext; caveats?: Caveat[] },
  ): PanelExport => ({
    title,
    spec,
    context: contextFromApplied(title, result?.applied_context, result?.caveats ?? []),
  });

  const areaSpec: QuerySpec = useMemo(
    () => ({
      metric: 'area',
      filters: [
        { dimension: 'crop', op: 'in' as const, values: [activeCrop] },
        ...(districts.length ? [{ dimension: 'district', op: 'in' as const, values: districts }] : []),
        ...(season ? [{ dimension: 'season', op: 'eq' as const, values: [season] }] : []),
      ],
      period: { from, to },
      limit: 10,
      include_records: false,
    }),
    [activeCrop, districts, season, from, to],
  );

  const prodSpec: QuerySpec = useMemo(
    () => ({
      metric: 'production',
      filters: [
        { dimension: 'crop', op: 'in' as const, values: [activeCrop] },
        ...(districts.length ? [{ dimension: 'district', op: 'in' as const, values: districts }] : []),
        ...(season ? [{ dimension: 'season', op: 'eq' as const, values: [season] }] : []),
      ],
      period: { from, to },
      limit: 10,
      include_records: false,
    }),
    [activeCrop, districts, season, from, to],
  );

  const yieldSpec: QuerySpec = useMemo(
    () => ({
      metric: 'yield_rate',
      filters: [
        { dimension: 'crop', op: 'in' as const, values: [activeCrop] },
        ...(districts.length ? [{ dimension: 'district', op: 'in' as const, values: districts }] : []),
        ...(season ? [{ dimension: 'season', op: 'eq' as const, values: [season] }] : []),
      ],
      period: { from, to },
      limit: 10,
      include_records: false,
    }),
    [activeCrop, districts, season, from, to],
  );

  const areaQuery = useQuery({ queryKey: ['ag-kpi-area', areaSpec], queryFn: () => api.query(areaSpec) });
  const prodQuery = useQuery({ queryKey: ['ag-kpi-prod', prodSpec], queryFn: () => api.query(prodSpec) });
  const yieldQuery = useQuery({ queryKey: ['ag-kpi-yield', yieldSpec], queryFn: () => api.query(yieldSpec) });

  useEffect(() => {
    if (prodQuery.data?.applied_context && onContextUpdate) {
      onContextUpdate(prodQuery.data.applied_context, prodQuery.data.caveats ?? []);
    }
  }, [prodQuery.data, onContextUpdate]);

  const areaVal = areaQuery.data?.rows[0]?.value;
  const prodVal = prodQuery.data?.rows[0]?.value;
  const yieldVal = yieldQuery.data?.rows[0]?.value;

  const cropName = cropDisplayName(prodQuery.data?.applied_context);

  // 2. District Comparison (Yield and Production) Query
  const districtAgSpec: QuerySpec = useMemo(
    () => ({
      metric: 'yield_rate',
      dimensions: ['district'],
      filters: [
        { dimension: 'crop', op: 'in' as const, values: [activeCrop] },
        ...(season ? [{ dimension: 'season', op: 'eq' as const, values: [season] }] : []),
      ],
      period: { from, to },
      order_by: { field: 'value', direction: 'desc' as const },
      limit: 30,
      include_records: false,
    }),
    [activeCrop, season, from, to],
  );

  const districtAgProdSpec: QuerySpec = useMemo(
    () => ({
      metric: 'production',
      dimensions: ['district'],
      filters: [
        { dimension: 'crop', op: 'in' as const, values: [activeCrop] },
        ...(season ? [{ dimension: 'season', op: 'eq' as const, values: [season] }] : []),
      ],
      period: { from, to },
      limit: 30,
      include_records: false,
    }),
    [activeCrop, season, from, to],
  );

  const districtYieldQuery = useQuery({
    queryKey: ['ag-district-yield', districtAgSpec],
    queryFn: () => api.query(districtAgSpec),
  });

  const districtProdQuery = useQuery({
    queryKey: ['ag-district-prod', districtAgProdSpec],
    queryFn: () => api.query(districtAgProdSpec),
  });

  const districtComparisonData = useMemo(() => {
    const yRows = (districtYieldQuery.data?.rows || []) as Array<{
      district: string;
      district_id: string;
      value: number;
      grain_source?: string;
    }>;
    const pRows = (districtProdQuery.data?.rows || []) as Array<{
      district: string;
      district_id: string;
      value: number;
    }>;
    const pMap = new Map(pRows.map((r) => [r.district_id, r.value]));

    return yRows.map((r) => ({
      district: r.district,
      district_id: r.district_id,
      yield_rate: Number(r.value.toFixed(2)),
      production_lakh_mt: Number(((pMap.get(r.district_id) || 0) / 1e6).toFixed(2)),
      isAggregated: r.grain_source === 'aggregated_from_blocks',
    }));
  }, [districtYieldQuery.data, districtProdQuery.data]);

  // 3. 32-Year Long-Run State Series Query (1993-94 to 2024-25 from fact_state_series)
  const stateSeriesSpec: QuerySpec = useMemo(
    () => ({
      metric: stateSeriesMetric,
      dimensions: ['agri_year'],
      filters: [
        { dimension: 'crop', op: 'in' as const, values: [activeCrop] },
        { dimension: 'grain_source', op: 'eq' as const, values: ['published_state'] },
        ...(season ? [{ dimension: 'season', op: 'eq' as const, values: [season] }] : []),
      ],
      period: { from: '1993-94', to: '2024-25' },
      order_by: { field: 'agri_year', direction: 'asc' as const },
      limit: 50,
      include_records: false,
    }),
    [stateSeriesMetric, activeCrop, season],
  );

  const stateSeriesQuery = useQuery({
    queryKey: ['ag-state-series', stateSeriesSpec],
    queryFn: () => api.query(stateSeriesSpec),
  });

  const stateSeriesFormatted = useMemo(() => {
    const rows = (stateSeriesQuery.data?.rows || []) as Array<{
      agri_year: string;
      value: number;
    }>;
    return rows.map((r) => {
      let displayValue = r.value;
      if (stateSeriesMetric === 'production') displayValue = r.value / 1e6; // lakh MT
      if (stateSeriesMetric === 'area') displayValue = r.value / 1e5; // lakh ha
      return {
        agri_year: r.agri_year,
        value: Number(displayValue.toFixed(2)),
        raw_value: r.value,
      };
    });
  }, [stateSeriesQuery.data, stateSeriesMetric]);

  // 4. Land-Use Composition Query for District
  const landUseSpec: QuerySpec = useMemo(
    () => ({
      metric: 'land_use_share_pct',
      dimensions: ['land_use_category'],
      filters: [
        { dimension: 'district', op: 'eq' as const, values: [landUseDistrict] },
      ],
      period: { from, to },
      order_by: { field: 'value', direction: 'desc' as const },
      limit: 20,
      include_records: false,
    }),
    [landUseDistrict, from, to],
  );

  const landUseQuery = useQuery({
    queryKey: ['ag-land-use-share', landUseSpec],
    queryFn: () => api.query(landUseSpec),
  });

  const landUseData = useMemo(() => {
    const shareRows = (landUseQuery.data?.rows || []) as Array<{
      land_use_category: string;
      value: number;
    }>;
    return shareRows
      .filter((r) => !NOT_NINE_FOLD.has(r.land_use_category) && r.value !== null)
      .map((r) => ({
        category: r.land_use_category,
        sharePct: Number(r.value.toFixed(1)),
      }));
  }, [landUseQuery.data]);

  return (
    <div className="flex flex-col gap-6">
      {/* KPI Cards Strip */}
      <div className="grid grid-cols-1 gap-4 sm:grid-cols-3">
        <StatCard
          label="Total Area"
          value={
            areaQuery.isLoading ? (
              '…'
            ) : areaVal !== undefined && areaVal !== null ? (
              <span title={`${Number(areaVal).toLocaleString('en-IN')} ha`}>
                {(Number(areaVal) / 1e5).toFixed(2)}
              </span>
            ) : (
              '—'
            )
          }
          unit="lakh ha"
          hint={
            areaVal ? (
              <span className="tabular-nums font-mono text-badge">
                <Figure>{Number(areaVal).toLocaleString('en-IN')}</Figure> ha, summed over {sumScope}
              </span>
            ) : (
              `Summed over ${sumScope}`
            )
          }
        />

        <StatCard
          label="Total Production"
          value={
            prodQuery.isLoading ? (
              '…'
            ) : prodVal !== undefined && prodVal !== null ? (
              <span title={`${Number(prodVal).toLocaleString('en-IN')} qtl`}>
                {(Number(prodVal) / 1e6).toFixed(2)}
              </span>
            ) : (
              '—'
            )
          }
          unit="lakh MT"
          hint={
            prodVal ? (
              <span className="tabular-nums font-mono text-badge">
                <Figure>{Number(prodVal).toLocaleString('en-IN')}</Figure> quintals, summed over {sumScope}
              </span>
            ) : (
              `Summed over ${sumScope}`
            )
          }
        />

        <StatCard
          label="State Yield Rate"
          value={
            yieldQuery.isLoading ? (
              '…'
            ) : yieldVal !== undefined && yieldVal !== null ? (
              Number(yieldVal).toFixed(2)
            ) : (
              '—'
            )
          }
          unit="qtl/ha"
          hint="Calculated as sum(prod) ÷ sum(area). Never an average of yields."
        />
      </div>

      {/* Hero Visual: Long-Run State Series (1993-94 to 2024-25, 32 years of genuine DE&S data) */}
      <Card
        title={
          <div className="flex flex-wrap items-center gap-2">
            <span>
              Long-Run State Historical Series{cropName ? `: ${cropName}` : ''}
              {season ? `, ${season} season` : ', all seasons'} (1993-94 to 2024-25)
            </span>
            <span className="rounded bg-primary-subtle px-2 py-0.5 text-caption font-semibold text-primary border border-primary/20">
              32 Years of Genuine DE&S Official Data
            </span>
          </div>
        }
        description="Continuous 32-year statistical record from fact_state_series. Every annual figure is genuine historical data published by DE&S Odisha."
        actions={
          <div className="flex flex-wrap items-center gap-2">
            <div className="inline-flex rounded border border-line p-0.5 text-caption">
              {(
                [
                  { id: 'production', label: 'Production (lakh MT)' },
                  { id: 'area', label: 'Area (lakh ha)' },
                  { id: 'yield_rate', label: 'Yield rate (qtl/ha)' },
                ] as const
              ).map((m) => (
                <button
                  key={m.id}
                  type="button"
                  onClick={() => onUpdateFilters({ stateSeriesMetric: m.id })}
                  className={`rounded px-2.5 py-1 font-medium transition-colors ${
                    stateSeriesMetric === m.id
                      ? 'bg-primary text-white'
                      : 'text-ink-muted hover:bg-surface-alt hover:text-ink'
                  }`}
                >
                  {m.label}
                </button>
              ))}
            </div>
            <ExportButton
              onClick={() =>
                onExport(
                  panelExport(
                    `Long-Run State Series (${stateSeriesMetric})`,
                    stateSeriesSpec,
                    stateSeriesQuery.data,
                  ),
                )
              }
            />
          </div>
        }
        chart
      >
        {stateSeriesQuery.isLoading && <LoadingState label="Querying 32 years of state series from DuckDB..." />}
        {stateSeriesQuery.error && (
          <ErrorState
            error={stateSeriesQuery.error}
            onRetry={() => void stateSeriesQuery.refetch()}
          />
        )}
        {!stateSeriesQuery.isLoading && !stateSeriesQuery.error && stateSeriesFormatted.length === 0 && (
          <EmptyState title="No records found" detail="No historical state series data for this crop selection." />
        )}
        {!stateSeriesQuery.isLoading && !stateSeriesQuery.error && stateSeriesFormatted.length > 0 && (
          <div className="h-80 w-full">
            <ResponsiveContainer width="100%" height="100%">
              <LineChart data={stateSeriesFormatted} margin={{ top: 10, right: 30, left: 15, bottom: 25 }}>
                <CartesianGrid strokeDasharray="3 3" vertical={false} opacity={0.5} stroke="var(--color-border)" />
                <XAxis
                  dataKey="agri_year"
                  tick={{ fontSize: 11, fill: 'var(--color-text-muted)' }}
                  angle={-45}
                  textAnchor="end"
                  interval={1}
                />
                <YAxis
                  tick={{ fontSize: 12, fill: 'var(--color-text-muted)' }}
                  unit={
                    stateSeriesMetric === 'production'
                      ? ' lakh MT'
                      : stateSeriesMetric === 'area'
                      ? ' lakh ha'
                      : ' qtl/ha'
                  }
                />
                <Tooltip
                  content={({ active, payload, label }) => {
                    if (!active || !payload?.length) return null;
                    const item = payload[0].payload as { agri_year: string; value: number; raw_value: number };
                    const unitLabel =
                      stateSeriesMetric === 'production'
                        ? 'lakh MT'
                        : stateSeriesMetric === 'area'
                        ? 'lakh ha'
                        : 'qtl/ha';
                    return (
                      <div className="rounded border border-line bg-surface p-2.5 shadow-md text-caption text-ink">
                        <div className="flex items-center justify-between gap-3 font-semibold">
                          <span>{label}</span>
                          <span className="text-ink-muted">Official DE&S</span>
                        </div>
                        <p className="mt-1 text-section font-semibold text-primary">
                          {item.value} {unitLabel}
                        </p>
                        <p className="text-badge text-ink-subtle">Click point to drill down into source report</p>
                      </div>
                    );
                  }}
                />
                <Line
                  type="monotone"
                  dataKey="value"
                  name={
                    stateSeriesMetric === 'production'
                      ? 'Production (lakh MT)'
                      : stateSeriesMetric === 'area'
                      ? 'Area (lakh ha)'
                      : 'Yield rate (qtl/ha)'
                  }
                  stroke={CHART_COLORS[0]}
                  strokeWidth={2.5}
                  dot={{ r: 3, fill: CHART_COLORS[0] }}
                  activeDot={{
                    r: 6,
                    onClick: (_, event) => {
                      const year = stateSeriesFormatted[(event as { activeIndex?: number })?.activeIndex || 0]?.agri_year;
                      onDrillDown(
                        {
                          metric: stateSeriesMetric,
                          filters: [
                            { dimension: 'crop', op: 'in', values: [activeCrop] },
                            { dimension: 'grain_source', op: 'eq', values: ['published_state'] },
                            { dimension: 'agri_year', op: 'eq', values: [year] },
                          ],
                          include_records: false,
                          limit: 50,
                        },
                        `DE&S State Series record for ${year} (${stateSeriesMetric})`,
                      );
                    },
                  }}
                />
              </LineChart>
            </ResponsiveContainer>
          </div>
        )}
      </Card>

      {/* District Comparison Grid: Yield Rate & Production */}
      <Card
        title={`District Yield & Production Comparison${cropName ? `: ${cropName}` : ''}`}
        description={`Yield rate and production by district, ${periodLabel}${season ? `, ${season} season` : ''}. Production is summed over the period; yield is total production divided by total area.`}
        actions={
          <ExportButton
            onClick={() =>
              onExport(
                panelExport(
                  'District Yield & Production Comparison',
                  districtAgSpec,
                  districtYieldQuery.data,
                ),
              )
            }
          />
        }
        chart
      >
        {districtYieldQuery.isLoading || districtProdQuery.isLoading ? (
          <LoadingState label="Loading district statistics..." />
        ) : districtComparisonData.length === 0 ? (
          <EmptyState title="No district records" detail="No data for this crop and period." />
        ) : (
          <div className="flex flex-col gap-4">
            <div className="h-80 w-full">
              <ResponsiveContainer width="100%" height="100%">
                <BarChart data={districtComparisonData.slice(0, 15)} margin={{ top: 10, right: 20, left: 10, bottom: 40 }}>
                  <CartesianGrid strokeDasharray="3 3" vertical={false} opacity={0.5} stroke="var(--color-border)" />
                  <XAxis
                    dataKey="district"
                    tick={{ fontSize: 12, fill: 'var(--color-text)' }}
                    angle={-35}
                    textAnchor="end"
                    interval={0}
                  />
                  <YAxis yAxisId="left" tick={{ fontSize: 12, fill: 'var(--color-text-muted)' }} unit=" qtl/ha" />
                  <YAxis
                    yAxisId="right"
                    orientation="right"
                    tick={{ fontSize: 12, fill: 'var(--color-text-muted)' }}
                    unit=" L MT"
                  />
                  <Tooltip
                    content={({ active, payload }) => {
                      if (!active || !payload?.length) return null;
                      const item = payload[0].payload as {
                        district: string;
                        district_id: string;
                        yield_rate: number;
                        production_lakh_mt: number;
                        isAggregated: boolean;
                      };
                      return (
                        <div className="rounded border border-line bg-surface p-2.5 shadow-md text-caption text-ink">
                          <div className="flex items-center justify-between gap-3 font-semibold">
                            <span>{item.district}</span>
                          </div>
                          <div className="mt-1 space-y-1">
                            <p className="text-primary font-medium">Yield Rate: {item.yield_rate} qtl/ha</p>
                            <p className="text-chart-2 font-medium">
                              Production: {item.production_lakh_mt} lakh MT
                            </p>
                          </div>
                          <p className="text-badge text-ink-subtle">Click to inspect underlying records</p>
                        </div>
                      );
                    }}
                  />
                  <Legend wrapperStyle={{ paddingTop: '10px', fontSize: '12px' }} />
                  <Bar
                    yAxisId="left"
                    dataKey="yield_rate"
                    name="Yield Rate (qtl/ha)"
                    fill={CHART_COLORS[0]}
                    onClick={(entry) => {
                      const d = entry as unknown as { district_id: string; district: string };
                      onDrillDown(
                        {
                          ...districtAgSpec,
                          filters: [
                            ...(districtAgSpec.filters || []),
                            { dimension: 'district', op: 'eq', values: [d.district_id] },
                          ],
                          include_records: false,
                          limit: 50,
                        },
                        `Supporting records: ${d.district} Yield Rate`,
                      );
                    }}
                    className="cursor-pointer"
                  />
                  <Bar
                    yAxisId="right"
                    dataKey="production_lakh_mt"
                    name="Production (lakh MT)"
                    fill={CHART_COLORS[1]}
                    onClick={(entry) => {
                      const d = entry as unknown as { district_id: string; district: string };
                      onDrillDown(
                        {
                          ...districtAgProdSpec,
                          filters: [
                            ...(districtAgProdSpec.filters || []),
                            { dimension: 'district', op: 'eq', values: [d.district_id] },
                          ],
                          include_records: false,
                          limit: 50,
                        },
                        `Supporting records: ${d.district} Production`,
                      );
                    }}
                    className="cursor-pointer"
                  />
                </BarChart>
              </ResponsiveContainer>
            </div>
          </div>
        )}
      </Card>

      {/* Lower Row: Land-Use Composition & Actual vs Forecast Panel */}
      <div className="grid grid-cols-1 gap-6 lg:grid-cols-2">
        {/* Land-Use Composition (Nine-fold Split) */}
        <Card
          title="Land-Use Composition (Nine-fold Classification)"
          description="The nine-fold classification, as shares of the district's total area under survey."
          actions={
            <div className="flex items-center gap-2">
              <label htmlFor="lu-dist-select" className="text-caption font-medium uppercase tracking-header text-ink-subtle">
                District:
              </label>
              <select
                id="lu-dist-select"
                value={landUseDistrict}
                onChange={(e) => onUpdateFilters({ landUseDistrict: e.target.value })}
                className="rounded border border-line bg-surface px-2 py-1 text-caption text-ink focus:border-primary focus:outline-none"
              >
                {ALL_DISTRICTS.map((d) => (
                  <option key={d.id} value={d.id}>
                    {d.name}
                  </option>
                ))}
              </select>
              <ExportButton
                onClick={() =>
                  onExport(panelExport('Land-Use Composition', landUseSpec, landUseQuery.data))
                }
              />
            </div>
          }
          chart
        >
          {landUseQuery.isLoading ? (
            <LoadingState label="Loading nine-fold land use data..." />
          ) : landUseData.length === 0 ? (
            <EmptyState title="No land use records" detail="Select another district or year." />
          ) : (
            <div className="flex flex-col gap-4">
              <div className="h-64 w-full">
                <ResponsiveContainer width="100%" height="100%">
                  <BarChart
                    data={landUseData}
                    layout="vertical"
                    margin={{ top: 5, right: 20, left: 100, bottom: 5 }}
                  >
                    <CartesianGrid strokeDasharray="3 3" horizontal={false} opacity={0.5} stroke="var(--color-border)" />
                    <XAxis type="number" tick={{ fontSize: 12, fill: 'var(--color-text-muted)' }} unit=" %" />
                    <YAxis
                      dataKey="category"
                      type="category"
                      tick={{ fontSize: 11, fill: 'var(--color-text)' }}
                      width={95}
                    />
                    <Tooltip
                      content={({ active, payload }) => {
                        if (!active || !payload?.length) return null;
                        const data = payload[0].payload as {
                          category: string;
                          sharePct: number;
                        };
                        return (
                          <div className="rounded border border-line bg-surface p-2 shadow-md text-caption text-ink">
                            <p className="font-semibold">{data.category}</p>
                            <p className="tabular-nums font-medium text-primary">
                              {data.sharePct}% of surveyed area
                            </p>
                          </div>
                        );
                      }}
                    />
                    <Bar
                      dataKey="sharePct"
                      fill={CHART_COLORS[0]}
                      onClick={(entry) => {
                        const c = entry as unknown as { category: string };
                        onDrillDown(
                          {
                            // The records behind a share are the land-use rows
                            // themselves, in hectares.
                            metric: 'land_use_share_pct',
                            dimensions: ['land_use_category'],
                            filters: [
                              { dimension: 'district', op: 'eq', values: [landUseDistrict] },
                              { dimension: 'land_use_category', op: 'eq', values: [c.category] },
                            ],
                            period: { from, to },
                            include_records: false,
                            limit: 50,
                          },
                          `Land-use fact rows: ${c.category}`,
                        );
                      }}
                      className="cursor-pointer"
                    >
                      {landUseData.map((_, i) => (
                        <Cell key={i} fill={CHART_COLORS[i % CHART_COLORS.length]} />
                      ))}
                    </Bar>
                  </BarChart>
                </ResponsiveContainer>
              </div>

              {/* Nine-fold Summary Table */}
              <div className="max-h-48 overflow-y-auto rounded border border-line">
                <table className="w-full text-left text-caption">
                  <thead className="border-b border-line bg-surface-alt font-semibold text-ink-subtle">
                    <tr>
                      <th className="px-3 py-1.5">Category</th>
                      <th className="px-3 py-1.5 text-right">Share (%)</th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-line bg-surface">
                    {landUseData.map((row) => (
                      <tr key={row.category} className="hover:bg-surface-alt/60">
                        <td className="px-3 py-1 text-ink">{row.category}</td>
                        <td className="px-3 py-1 text-right tabular-nums font-semibold text-primary">
                          {row.sharePct}%
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </div>
          )}
        </Card>

        {/* Published model estimates, and the grounded narrative for this view. */}
        <ActualVsForecastPanel
          onExport={() =>
            onExport({
              // This panel reads GET /dashboard/forecasts, which is not a query
              // spec, so it exports by payload -- and without the panel's rows.
              title: 'Actual against model estimate',
              spec: null,
              context: toExportContext({ panelTitle: 'Actual against model estimate' }),
            })
          }
        />

        <NarrativePanel
          spec={prodSpec}
          title="Agriculture dashboard narrative"
          onExport={onExport}
        />
      </div>
    </div>
  );
}
