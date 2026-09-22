import { useEffect, useMemo, useState } from 'react';
import { useQuery } from '@tanstack/react-query';
import {
  Bar,
  BarChart,
  CartesianGrid,
  Cell,
  Legend,
  Line,
  LineChart,
  ReferenceLine,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from 'recharts';

import { api, type AppliedContext, type Caveat, type QuerySpec } from '@/api/client';
import { Card, Figure, StatCard } from '@/components/primitives';
import { EmptyState, ErrorState, LoadingState } from '@/components/states';
import { NarrativePanel } from '@/features/dashboard/NarrativePanel';
import {
  CHART_COLORS,
  CHART_INK,
  DUAL_PRICE_CROPS,
  PADDY_CROP_ID,
} from '../constants';
import { ExportButton } from '@/components/ExportButton';
import type { DashboardFilters } from '../useDashboardFilters';

export interface PriceDashboardProps {
  filters: DashboardFilters;
  onDrillDown: (spec: QuerySpec, title: string) => void;
  onExport: (title: string, rowCount?: number) => void;
  onContextUpdate?: (context: AppliedContext, caveats: Caveat[]) => void;
}

export function PriceDashboard({ filters, onDrillDown, onExport, onContextUpdate }: PriceDashboardProps) {
  const { from, to, districts, crops, priceType } = filters;
  const isPaddyInScope = crops.includes(PADDY_CROP_ID);

  // 1. KPI Queries
  const avgPriceSpec: QuerySpec = useMemo(
    () => ({
      metric: 'avg_price',
      filters: [
        ...(crops.length ? [{ dimension: 'crop', op: 'in' as const, values: crops }] : []),
        ...(districts.length ? [{ dimension: 'district', op: 'in' as const, values: districts }] : []),
        { dimension: 'price_type', op: 'eq' as const, values: [priceType] },
        { dimension: 'data_origin', op: 'in' as const, values: ['official', 'synthetic'] },
      ],
      period: { from, to },
      limit: 10,
      include_records: false,
    }),
    [crops, districts, priceType, from, to],
  );

  const yoyPriceSpec: QuerySpec = useMemo(
    () => ({
      metric: 'price_yoy_pct',
      dimensions: ['agri_year'],
      filters: [
        ...(crops.length ? [{ dimension: 'crop', op: 'in' as const, values: crops }] : []),
        ...(districts.length ? [{ dimension: 'district', op: 'in' as const, values: districts }] : []),
        { dimension: 'price_type', op: 'eq' as const, values: [priceType] },
        { dimension: 'data_origin', op: 'in' as const, values: ['official', 'synthetic'] },
      ],
      period: { from, to },
      order_by: { field: 'agri_year', direction: 'desc' as const },
      limit: 5,
      include_records: false,
    }),
    [crops, districts, priceType, from, to],
  );

  const fhpGapSpec: QuerySpec = useMemo(
    () => ({
      metric: 'fhp_wholesale_gap',
      filters: [
        ...(crops.length ? [{ dimension: 'crop', op: 'in' as const, values: crops }] : []),
        ...(districts.length ? [{ dimension: 'district', op: 'in' as const, values: districts }] : []),
        { dimension: 'data_origin', op: 'in' as const, values: ['official', 'synthetic'] },
      ],
      period: { from, to },
      limit: 10,
      include_records: false,
    }),
    [crops, districts, from, to],
  );

  const fhpGapPctSpec: QuerySpec = useMemo(
    () => ({
      metric: 'fhp_wholesale_gap_pct',
      filters: [
        ...(crops.length ? [{ dimension: 'crop', op: 'in' as const, values: crops }] : []),
        ...(districts.length ? [{ dimension: 'district', op: 'in' as const, values: districts }] : []),
        { dimension: 'data_origin', op: 'in' as const, values: ['official', 'synthetic'] },
      ],
      period: { from, to },
      limit: 10,
      include_records: false,
    }),
    [crops, districts, from, to],
  );

  const avgPriceQuery = useQuery({
    queryKey: ['price-kpi-avg', avgPriceSpec],
    queryFn: () => api.query(avgPriceSpec),
  });

  const yoyPriceQuery = useQuery({
    queryKey: ['price-kpi-yoy', yoyPriceSpec],
    queryFn: () => api.query(yoyPriceSpec),
  });

  const fhpGapQuery = useQuery({
    queryKey: ['price-kpi-gap', fhpGapSpec],
    queryFn: () => api.query(fhpGapSpec),
  });

  const fhpGapPctQuery = useQuery({
    queryKey: ['price-kpi-gap-pct', fhpGapPctSpec],
    queryFn: () => api.query(fhpGapPctSpec),
  });

  // 2. Trend Chart Query (Monthly series over time)
  const trendDimension = crops.length > 1 ? 'crop' : 'district';
  const trendSpec: QuerySpec = useMemo(
    () => ({
      metric: 'avg_price',
      dimensions: ['month', trendDimension],
      filters: [
        ...(crops.length ? [{ dimension: 'crop', op: 'in' as const, values: crops.slice(0, 6) }] : []),
        ...(districts.length
          ? [{ dimension: 'district', op: 'in' as const, values: districts.slice(0, 6) }]
          : []),
        { dimension: 'price_type', op: 'eq' as const, values: [priceType] },
        { dimension: 'data_origin', op: 'in' as const, values: ['official', 'synthetic'] },
      ],
      period: { from, to },
      order_by: { field: 'month', direction: 'asc' as const },
      limit: 1000,
      include_records: false,
    }),
    [trendDimension, crops, districts, priceType, from, to],
  );

  const trendQuery = useQuery({
    queryKey: ['price-trend', trendSpec],
    queryFn: () => api.query(trendSpec),
  });

  // Transform trend rows to Recharts friendly format
  const { trendData, seriesKeys } = useMemo(() => {
    const rows = (trendQuery.data?.rows || []) as Array<{
      month?: string;
      crop?: string;
      district?: string;
      value: number | null;
      grain_source?: string;
    }>;

    const keySet = new Set<string>();
    const monthMap = new Map<string, Record<string, unknown>>();

    for (const r of rows) {
      if (!r.month) continue;
      const key = trendDimension === 'crop' ? r.crop || 'Crop' : r.district || 'District';
      keySet.add(key);

      const existing = monthMap.get(r.month) || { month: r.month, isSynthetic: r.month >= '2019-07' };
      existing[key] = r.value;
      monthMap.set(r.month, existing);
    }

    const sortedMonths = Array.from(monthMap.keys()).sort();
    const formatted = sortedMonths.map((m) => monthMap.get(m)!);

    return { trendData: formatted, seriesKeys: Array.from(keySet).slice(0, 8) };
  }, [trendQuery.data, trendDimension]);

  // 3. District Comparison Query
  const districtSpec: QuerySpec = useMemo(
    () => ({
      metric: 'avg_price',
      dimensions: ['district'],
      filters: [
        ...(crops.length
          ? [{ dimension: 'crop', op: 'in' as const, values: [crops[0]] }]
          : [{ dimension: 'crop', op: 'in' as const, values: [PADDY_CROP_ID] }]),
        { dimension: 'price_type', op: 'eq' as const, values: [priceType] },
        { dimension: 'data_origin', op: 'in' as const, values: ['official', 'synthetic'] },
      ],
      period: { from, to },
      order_by: { field: 'value', direction: 'desc' as const },
      limit: 30,
      include_records: false,
    }),
    [crops, priceType, from, to],
  );

  const districtQuery = useQuery({
    queryKey: ['price-district-comp', districtSpec],
    queryFn: () => api.query(districtSpec),
  });

  // 4. Crop Comparison Query
  const cropSpec: QuerySpec = useMemo(
    () => ({
      metric: 'avg_price',
      dimensions: ['crop'],
      filters: [
        ...(districts.length ? [{ dimension: 'district', op: 'in' as const, values: districts }] : []),
        { dimension: 'price_type', op: 'eq' as const, values: [priceType] },
        { dimension: 'data_origin', op: 'in' as const, values: ['official', 'synthetic'] },
      ],
      period: { from, to },
      order_by: { field: 'value', direction: 'desc' as const },
      limit: 30,
      include_records: false,
    }),
    [districts, priceType, from, to],
  );

  const cropQuery = useQuery({
    queryKey: ['price-crop-comp', cropSpec],
    queryFn: () => api.query(cropSpec),
  });

  // 5. Farm Harvest vs Wholesale Paired View Query (13 crops)
  const pairedCropsList = DUAL_PRICE_CROPS.map((c) => c.id);
  const farmHarvestPairedSpec: QuerySpec = useMemo(
    () => ({
      metric: 'avg_price',
      dimensions: ['crop'],
      filters: [
        { dimension: 'crop', op: 'in' as const, values: pairedCropsList },
        ...(districts.length ? [{ dimension: 'district', op: 'in' as const, values: districts }] : []),
        { dimension: 'price_type', op: 'eq' as const, values: ['farm_harvest'] },
        { dimension: 'data_origin', op: 'in' as const, values: ['official', 'synthetic'] },
      ],
      period: { from, to },
      limit: 30,
      include_records: false,
    }),
    [pairedCropsList, districts, from, to],
  );

  const wholesalePairedSpec: QuerySpec = useMemo(
    () => ({
      metric: 'avg_price',
      dimensions: ['crop'],
      filters: [
        { dimension: 'crop', op: 'in' as const, values: pairedCropsList },
        ...(districts.length ? [{ dimension: 'district', op: 'in' as const, values: districts }] : []),
        { dimension: 'price_type', op: 'eq' as const, values: ['wholesale'] },
        { dimension: 'data_origin', op: 'in' as const, values: ['official', 'synthetic'] },
      ],
      period: { from, to },
      limit: 30,
      include_records: false,
    }),
    [pairedCropsList, districts, from, to],
  );

  const farmHarvestPairedQuery = useQuery({
    queryKey: ['price-paired-fhp', farmHarvestPairedSpec],
    queryFn: () => api.query(farmHarvestPairedSpec),
  });

  const wholesalePairedQuery = useQuery({
    queryKey: ['price-paired-ws', wholesalePairedSpec],
    queryFn: () => api.query(wholesalePairedSpec),
  });

  const pairedData = useMemo(() => {
    const fhpRows = (farmHarvestPairedQuery.data?.rows || []) as Array<{ crop: string; crop_id: string; value: number }>;
    const wsRows = (wholesalePairedQuery.data?.rows || []) as Array<{ crop: string; crop_id: string; value: number }>;

    const wsMap = new Map(wsRows.map((r) => [r.crop, r.value]));

    return fhpRows
      .map((r) => {
        const ws = wsMap.get(r.crop);
        const fhp = r.value;
        const gap = ws !== undefined && fhp !== null ? ws - fhp : 0;
        const gapPct = fhp ? (gap / fhp) * 100 : 0;
        return {
          crop: r.crop,
          crop_id: r.crop_id,
          farm_harvest: fhp,
          wholesale: ws ?? null,
          gap: Number(gap.toFixed(2)),
          gapPct: Number(gapPct.toFixed(1)),
        };
      })
      .sort((a, b) => b.gap - a.gap);
  }, [farmHarvestPairedQuery.data, wholesalePairedQuery.data]);

  // 6. Records Grid Query
  const [gridPage, setGridPage] = useState(1);
  const gridSpec: QuerySpec = useMemo(
    () => ({
      metric: 'avg_price',
      dimensions: ['agri_year', 'month', 'district', 'crop', 'price_type'],
      filters: [
        ...(crops.length ? [{ dimension: 'crop', op: 'in' as const, values: crops }] : []),
        ...(districts.length ? [{ dimension: 'district', op: 'in' as const, values: districts }] : []),
        { dimension: 'price_type', op: 'eq' as const, values: [priceType] },
        { dimension: 'data_origin', op: 'in' as const, values: ['official', 'synthetic'] },
      ],
      period: { from, to },
      order_by: { field: 'month', direction: 'desc' as const },
      limit: 100,
      include_records: false,
    }),
    [crops, districts, priceType, from, to],
  );

  const gridQuery = useQuery({
    queryKey: ['price-records-grid', gridSpec],
    queryFn: () => api.query(gridSpec),
  });

  useEffect(() => {
    if (avgPriceQuery.data?.applied_context && onContextUpdate) {
      onContextUpdate(avgPriceQuery.data.applied_context, avgPriceQuery.data.caveats ?? []);
    }
  }, [avgPriceQuery.data, onContextUpdate]);

  // KPI computations
  const avgVal = avgPriceQuery.data?.rows[0]?.value as number | undefined;
  const yoyVal = yoyPriceQuery.data?.rows[0]?.value as number | undefined;
  const gapVal = fhpGapQuery.data?.rows[0]?.value as number | undefined;
  const gapPctVal = fhpGapPctQuery.data?.rows[0]?.value as number | undefined;

  const districtRows = (districtQuery.data?.rows || []) as Array<{ district: string; district_id: string; value: number }>;
  const cropRows = (cropQuery.data?.rows || []) as Array<{ crop: string; crop_id: string; value: number }>;

  return (
    <div className="flex flex-col gap-6">
      {/* MSP Substitution Caveat Banner for Paddy */}
      {isPaddyInScope && (
        <div
          role="alert"
          className="flex items-start gap-3 rounded border border-warning/40 bg-warning-bg p-3.5 text-body text-ink"
        >
          <span className="text-warning text-section font-bold">⚠</span>
          <div className="space-y-1">
            <h4 className="font-semibold text-warning">
              Paddy Price Methodology Caveat: Minimum Support Price (MSP) Substituted
            </h4>
            <p className="text-caption text-ink-muted leading-relaxed">
              In published DE&S statistics, official paddy prices represent administrative Minimum Support Prices
              rather than freely observed district market prices. Farm harvest and wholesale series for paddy are
              pegged to MSP guidelines for Odisha.
            </p>
          </div>
        </div>
      )}

      {/* KPI Cards Strip */}
      <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-4">
        <StatCard
          label={`Average Price (${priceType.replace('_', ' ')})`}
          value={
            avgPriceQuery.isLoading ? (
              '…'
            ) : avgVal !== undefined && avgVal !== null ? (
              Number(avgVal).toLocaleString('en-IN', { maximumFractionDigits: 1 })
            ) : (
              '—'
            )
          }
          unit="Rs/qtl"
          hint={`Selection average across ${districts.length || 30} districts`}
        />

        <StatCard
          label="Year-on-Year Movement"
          value={
            yoyPriceQuery.isLoading ? (
              '…'
            ) : yoyVal !== undefined && yoyVal !== null ? (
              `${yoyVal > 0 ? '+' : ''}${Number(yoyVal).toFixed(1)}%`
            ) : (
              '—'
            )
          }
          unit={yoyVal !== null && yoyVal !== undefined ? 'YoY' : undefined}
          hint={
            yoyPriceQuery.data?.rows[0]?.agri_year
              ? `Compared to preceding year (${yoyPriceQuery.data.rows[0].agri_year})`
              : 'Requires prior period'
          }
        />

        <StatCard
          label="Wholesale Premium over Farm Harvest"
          value={
            fhpGapQuery.isLoading || fhpGapPctQuery.isLoading ? (
              '…'
            ) : gapVal !== undefined && gapVal !== null ? (
              `+${Number(gapVal).toLocaleString('en-IN', { maximumFractionDigits: 0 })}`
            ) : (
              '—'
            )
          }
          unit="Rs/qtl"
          hint={
            gapPctVal !== undefined && gapPctVal !== null
              ? `Wholesale is +${Number(gapPctVal).toFixed(1)}% over farm harvest`
              : 'Gap across common crops'
          }
        />

        <StatCard
          label="Scope in View"
          value={<Figure>{districts.length === 0 ? '30' : String(districts.length)}</Figure>}
          unit="districts"
          hint={`${crops.length} crop${crops.length === 1 ? '' : 's'} · ${from} to ${to}`}
        />
      </div>

      {/* Primary Chart: Monthly Price Over Time with Official / Synthetic Boundary */}
      <Card
        title="Monthly Price Trend (2013-14 to 2024-25)"
        description="Official DE&S price statistics end at 2018-19. Series post-2018-19 are synthetic monthly fits, visually differentiated with dashed lines."
        actions={
          <div className="flex items-center gap-2">
            <span className="inline-flex items-center gap-1 text-caption text-ink-muted">
              <span className="h-0.5 w-4 bg-chart-1"></span> Official (solid)
            </span>
            <span className="inline-flex items-center gap-1 text-caption text-ink-muted">
              <span className="h-0.5 w-4 border-b border-dashed border-chart-1"></span> Synthetic (dashed)
            </span>
            <ExportButton onClick={() => onExport('Monthly Price Trend', trendQuery.data?.applied_context.row_count)} />
          </div>
        }
        chart
      >
        {trendQuery.isLoading && <LoadingState label="Loading monthly price series..." />}
        {trendQuery.error && (
          <ErrorState
            error={trendQuery.error}
            onRetry={() => void trendQuery.refetch()}
          />
        )}
        {!trendQuery.isLoading && !trendQuery.error && trendData.length === 0 && (
          <EmptyState
            title="No price records for this period"
            detail="Check that the crop and districts are priced in the selected years."
          />
        )}
        {!trendQuery.isLoading && !trendQuery.error && trendData.length > 0 && (
          <div className="h-80 w-full">
            <ResponsiveContainer width="100%" height="100%">
              <LineChart data={trendData} margin={{ top: 10, right: 30, left: 10, bottom: 20 }}>
                <CartesianGrid strokeDasharray="3 3" vertical={false} opacity={0.5} stroke="var(--color-border)" />
                <XAxis
                  dataKey="month"
                  tick={{ fontSize: 12, fill: 'var(--color-text-muted)' }}
                  tickLine={false}
                  interval="preserveStartEnd"
                />
                <YAxis
                  tick={{ fontSize: 12, fill: 'var(--color-text-muted)' }}
                  tickLine={false}
                  unit=" Rs"
                  domain={['auto', 'auto']}
                />
                <Tooltip
                  content={({ active, payload, label }) => {
                    if (!active || !payload?.length) return null;
                    return (
                      <div className="rounded border border-line bg-surface p-2.5 shadow-md text-caption text-ink">
                        <div className="flex items-center justify-between gap-4 font-semibold">
                          <span>{label}</span>
                        </div>
                        <div className="mt-1.5 space-y-1">
                          {payload.map((entry) => (
                            <div key={entry.name} className="flex items-center justify-between gap-4">
                              <span style={{ color: entry.color }} className="font-medium">
                                {entry.name}:
                              </span>
                              <span className="font-semibold tabular-nums">
                                ₹{Number(entry.value).toLocaleString('en-IN')} / qtl
                              </span>
                            </div>
                          ))}
                        </div>
                        <p className="mt-1 text-badge text-ink-subtle">Click point to drill down into fact rows</p>
                      </div>
                    );
                  }}
                />
                <Legend wrapperStyle={{ paddingTop: '10px', fontSize: '12px' }} />
                {/* Official vs Synthetic 2018-19 Boundary Line */}
                <ReferenceLine
                  x="2019-06"
                  stroke="var(--prov-synthetic)"
                  strokeDasharray="4 4"
                  label={{
                    value: '2018-19: Official data ends ➔ Synthetic begins',
                    position: 'top',
                    fill: 'var(--prov-synthetic)',
                    fontSize: 12,
                    fontWeight: 500,
                  }}
                />
                {seriesKeys.map((key, i) => {
                  const color = CHART_COLORS[i % CHART_COLORS.length];
                  return (
                    <Line
                      key={key}
                      type="monotone"
                      dataKey={key}
                      name={key}
                      stroke={color}
                      strokeWidth={2}
                      dot={false}
                      activeDot={{
                        r: 5,
                        onClick: (_, event) => {
                          const month = trendData[(event as { activeIndex?: number })?.activeIndex || 0]?.month as string;
                          onDrillDown(
                            {
                              ...trendSpec,
                              filters: [
                                ...(trendSpec.filters || []),
                                { dimension: 'month', op: 'eq', values: [month] },
                              ],
                              limit: 100,
                            },
                            `Drill-down: ${key} price for ${month}`,
                          );
                        },
                      }}
                    />
                  );
                })}
              </LineChart>
            </ResponsiveContainer>
          </div>
        )}
      </Card>

      {/* Two Comparison Panels Grid: District Comparison & Crop Comparison */}
      <div className="grid grid-cols-1 gap-6 lg:grid-cols-2">
        {/* District Comparison Bar Chart */}
        <Card
          title={`Average Price by District (${crops.length ? crops[0] : PADDY_CROP_ID})`}
          description="Ranked average price across districts for selected crop. Leaders and laggards highlighted."
          actions={
            <ExportButton
              onClick={() => onExport('District Price Comparison', districtRows.length)}
            />
          }
          chart
        >
          {districtQuery.isLoading && <LoadingState label="Ranking districts..." />}
          {districtQuery.error && (
            <ErrorState
              error={districtQuery.error}
              onRetry={() => void districtQuery.refetch()}
            />
          )}
          {!districtQuery.isLoading && !districtQuery.error && districtRows.length === 0 && (
            <EmptyState title="No district records" detail="No data for this crop and period." />
          )}
          {!districtQuery.isLoading && !districtQuery.error && districtRows.length > 0 && (
            <div className="flex flex-col gap-3">
              <div className="flex items-center justify-between text-caption text-ink-muted">
                <span>
                  Leading: <strong className="text-ink">{districtRows[0]?.district}</strong> (₹
                  {Math.round(districtRows[0]?.value).toLocaleString('en-IN')})
                </span>
                <span>
                  Lagging: <strong className="text-ink">{districtRows[districtRows.length - 1]?.district}</strong> (₹
                  {Math.round(districtRows[districtRows.length - 1]?.value).toLocaleString('en-IN')})
                </span>
              </div>
              <div className="h-72 w-full">
                <ResponsiveContainer width="100%" height="100%">
                  <BarChart
                    data={districtRows.slice(0, 15)}
                    layout="vertical"
                    margin={{ top: 5, right: 20, left: 60, bottom: 5 }}
                  >
                    <CartesianGrid strokeDasharray="3 3" horizontal={false} opacity={0.5} stroke="var(--color-border)" />
                    <XAxis type="number" tick={{ fontSize: 12, fill: 'var(--color-text-muted)' }} unit=" ₹" />
                    <YAxis
                      dataKey="district"
                      type="category"
                      tick={{ fontSize: 12, fill: 'var(--color-text)' }}
                      width={65}
                    />
                    <Tooltip
                      content={({ active, payload }) => {
                        if (!active || !payload?.length) return null;
                        const data = payload[0].payload as { district: string; district_id: string; value: number };
                        return (
                          <div className="rounded border border-line bg-surface p-2 shadow-md text-caption text-ink">
                            <p className="font-semibold">{data.district}</p>
                            <p className="tabular-nums font-medium">₹{Number(data.value).toLocaleString('en-IN')} / qtl</p>
                            <p className="text-badge text-ink-subtle">Click bar to inspect records</p>
                          </div>
                        );
                      }}
                    />
                    <Bar
                      dataKey="value"
                      fill={CHART_COLORS[0]}
                      onClick={(data) => {
                        const d = data as unknown as { district_id: string; district: string };
                        onDrillDown(
                          {
                            ...districtSpec,
                            filters: [
                              ...(districtSpec.filters || []),
                              { dimension: 'district', op: 'eq', values: [d.district_id] },
                            ],
                            limit: 100,
                          },
                          `Records for ${d.district} (${districtSpec.metric})`,
                        );
                      }}
                      className="cursor-pointer"
                    >
                      {districtRows.slice(0, 15).map((entry, index) => (
                        <Cell
                          key={entry.district_id}
                          fill={
                            index === 0
                              ? CHART_INK.success // green leader
                              : index === districtRows.length - 1
                              ? CHART_INK.error // red laggard
                              : CHART_COLORS[0]
                          }
                        />
                      ))}
                    </Bar>
                  </BarChart>
                </ResponsiveContainer>
              </div>
            </div>
          )}
        </Card>

        {/* Crop Comparison Bar Chart */}
        <Card
          title="Price Comparison Across Commodities"
          description="Average price in Rs/quintal across selected crops."
          actions={<ExportButton onClick={() => onExport('Crop Price Comparison', cropRows.length)} />}
          chart
        >
          {cropQuery.isLoading && <LoadingState label="Comparing crops..." />}
          {cropQuery.error && (
            <ErrorState
              error={cropQuery.error}
              onRetry={() => void cropQuery.refetch()}
            />
          )}
          {!cropQuery.isLoading && !cropQuery.error && cropRows.length === 0 && (
            <EmptyState title="No crop data" detail="No data for selected crops." />
          )}
          {!cropQuery.isLoading && !cropQuery.error && cropRows.length > 0 && (
            <div className="h-80 w-full">
              <ResponsiveContainer width="100%" height="100%">
                <BarChart data={cropRows} margin={{ top: 10, right: 20, left: 10, bottom: 40 }}>
                  <CartesianGrid strokeDasharray="3 3" vertical={false} opacity={0.5} stroke="var(--color-border)" />
                  <XAxis
                    dataKey="crop"
                    tick={{ fontSize: 12, fill: 'var(--color-text)' }}
                    angle={-40}
                    textAnchor="end"
                    interval={0}
                  />
                  <YAxis tick={{ fontSize: 12, fill: 'var(--color-text-muted)' }} unit=" ₹" />
                  <Tooltip
                    content={({ active, payload }) => {
                      if (!active || !payload?.length) return null;
                      const data = payload[0].payload as { crop: string; crop_id: string; value: number };
                      return (
                        <div className="rounded border border-line bg-surface p-2 shadow-md text-caption text-ink">
                          <p className="font-semibold">{data.crop}</p>
                          <p className="tabular-nums font-medium">₹{Number(data.value).toLocaleString('en-IN')} / qtl</p>
                          <p className="text-badge text-ink-subtle">Click bar to drill down</p>
                        </div>
                      );
                    }}
                  />
                  <Bar
                    dataKey="value"
                    fill={CHART_COLORS[1]}
                    onClick={(data) => {
                      const c = data as unknown as { crop_id: string; crop: string };
                      onDrillDown(
                        {
                          ...cropSpec,
                          filters: [
                            ...(cropSpec.filters || []),
                            { dimension: 'crop', op: 'eq', values: [c.crop_id] },
                          ],
                          limit: 100,
                        },
                        `Fact rows for ${c.crop}`,
                      );
                    }}
                    className="cursor-pointer"
                  />
                </BarChart>
              </ResponsiveContainer>
            </div>
          )}
        </Card>
      </div>

      {/* Farm Harvest vs Wholesale Paired Comparison for 13 crops */}
      <Card
        title="Farm Harvest vs Wholesale Price Spread (13 Common Crops)"
        description="Pairwise comparison for commodities published in both price streams. The gap represents the wholesale trading premium over harvest prices."
        actions={
          <ExportButton
            onClick={() => onExport('Farm Harvest vs Wholesale Paired View', pairedData.length)}
          />
        }
        chart
      >
        {farmHarvestPairedQuery.isLoading || wholesalePairedQuery.isLoading ? (
          <LoadingState label="Calculating harvest and wholesale gap..." />
        ) : pairedData.length === 0 ? (
          <EmptyState title="No paired records" detail="No overlapping price data for these crops." />
        ) : (
          <div className="flex flex-col gap-3">
            <div className="h-80 w-full">
              <ResponsiveContainer width="100%" height="100%">
                <BarChart data={pairedData} margin={{ top: 10, right: 20, left: 10, bottom: 40 }}>
                  <CartesianGrid strokeDasharray="3 3" vertical={false} opacity={0.5} stroke="var(--color-border)" />
                  <XAxis
                    dataKey="crop"
                    tick={{ fontSize: 12, fill: 'var(--color-text)' }}
                    angle={-35}
                    textAnchor="end"
                    interval={0}
                  />
                  <YAxis tick={{ fontSize: 12, fill: 'var(--color-text-muted)' }} unit=" ₹" />
                  <Tooltip
                    content={({ active, payload }) => {
                      if (!active || !payload?.length) return null;
                      const item = payload[0].payload as {
                        crop: string;
                        farm_harvest: number;
                        wholesale: number;
                        gap: number;
                        gapPct: number;
                      };
                      return (
                        <div className="rounded border border-line bg-surface p-2.5 shadow-md text-caption text-ink">
                          <p className="font-semibold text-title">{item.crop}</p>
                          <div className="mt-1 space-y-1">
                            <p className="text-primary font-medium">
                              Wholesale: ₹{item.wholesale?.toLocaleString('en-IN')} / qtl
                            </p>
                            <p className="text-chart-2 font-medium">
                              Farm Harvest: ₹{item.farm_harvest?.toLocaleString('en-IN')} / qtl
                            </p>
                            <p className="font-semibold text-ink border-t border-line pt-1">
                              Spread Gap: ₹{item.gap.toLocaleString('en-IN')} ({item.gapPct > 0 ? '+' : ''}
                              {item.gapPct}%)
                            </p>
                          </div>
                        </div>
                      );
                    }}
                  />
                  <Legend wrapperStyle={{ paddingTop: '10px', fontSize: '12px' }} />
                  <Bar
                    dataKey="farm_harvest"
                    name="Farm Harvest Price"
                    fill={CHART_COLORS[1]}
                    onClick={(entry) => {
                      const c = entry as unknown as { crop_id: string; crop: string };
                      onDrillDown(
                        {
                          metric: 'avg_price',
                          filters: [
                            { dimension: 'crop', op: 'in', values: [c.crop_id] },
                            { dimension: 'price_type', op: 'eq', values: ['farm_harvest'] },
                          ],
                          period: { from, to },
                          limit: 50,
                          include_records: false,
                        },
                        `Farm harvest fact rows: ${c.crop}`,
                      );
                    }}
                    className="cursor-pointer"
                  />
                  <Bar
                    dataKey="wholesale"
                    name="Wholesale Price"
                    fill={CHART_COLORS[0]}
                    onClick={(entry) => {
                      const c = entry as unknown as { crop_id: string; crop: string };
                      onDrillDown(
                        {
                          metric: 'avg_price',
                          filters: [
                            { dimension: 'crop', op: 'in', values: [c.crop_id] },
                            { dimension: 'price_type', op: 'eq', values: ['wholesale'] },
                          ],
                          period: { from, to },
                          limit: 50,
                          include_records: false,
                        },
                        `Wholesale fact rows: ${c.crop}`,
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

      {/* Records Grid */}
      <Card
        title="Filtered Price Records"
        description="Underlying price records from DuckDB analytics.fact_price with provenance."
        actions={<ExportButton onClick={() => onExport('Filtered Price Records', gridQuery.data?.rows.length)} />}
      >
        {gridQuery.isLoading && <LoadingState label="Loading records grid..." />}
        {gridQuery.error && (
          <ErrorState
            error={gridQuery.error}
            onRetry={() => void gridQuery.refetch()}
          />
        )}
        {!gridQuery.isLoading && !gridQuery.error && (gridQuery.data?.rows.length || 0) === 0 && (
          <EmptyState title="No rows" detail="No matching price records found for current filters." />
        )}
        {!gridQuery.isLoading && !gridQuery.error && (gridQuery.data?.rows.length || 0) > 0 && (
          <div className="flex flex-col gap-3">
            <div className="overflow-x-auto rounded border border-line">
              <table className="w-full text-left text-body">
                <thead className="border-b border-line bg-surface-alt text-caption font-semibold uppercase tracking-header text-ink-subtle">
                  <tr>
                    <th className="px-3 py-2">Year / Month</th>
                    <th className="px-3 py-2">District</th>
                    <th className="px-3 py-2">Commodity</th>
                    <th className="px-3 py-2">Price Type</th>
                    <th className="px-3 py-2 text-right">Price (₹/qtl)</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-line bg-surface">
                  {gridQuery.data!.rows
                    .slice((gridPage - 1) * 15, gridPage * 15)
                    .map((row, index) => {
                      const r = row as {
                        agri_year?: string;
                        month?: string;
                        district?: string;
                        district_id?: string;
                        crop?: string;
                        crop_id?: string;
                        price_type?: string;
                        value: number;
                        grain_source?: string;
                      };
                      return (
                        <tr
                          key={index}
                          onClick={() => {
                            onDrillDown(
                              {
                                metric: 'avg_price',
                                filters: [
                                  ...(r.crop_id ? [{ dimension: 'crop', op: 'in' as const, values: [r.crop_id] }] : []),
                                  ...(r.district_id
                                    ? [{ dimension: 'district', op: 'in' as const, values: [r.district_id] }]
                                    : []),
                                  ...(r.month ? [{ dimension: 'month', op: 'eq' as const, values: [r.month] }] : []),
                                ],
                                limit: 50,
                                include_records: false,
                              },
                              `Record details: ${r.crop || 'Crop'} - ${r.district || 'District'} (${r.month || r.agri_year})`,
                            );
                          }}
                          className="cursor-pointer hover:bg-surface-alt/70"
                        >
                          <td className="whitespace-nowrap px-3 py-2 text-caption text-ink font-medium">
                            <Figure>{r.month || r.agri_year || '—'}</Figure>
                          </td>
                          <td className="px-3 py-2 font-medium text-ink">{r.district || '—'}</td>
                          <td className="px-3 py-2 text-ink">{r.crop || '—'}</td>
                          <td className="px-3 py-2 text-caption text-ink-muted capitalize">
                            {(r.price_type || priceType).replace('_', ' ')}
                          </td>
                          <td className="whitespace-nowrap px-3 py-2 text-right font-semibold text-ink">
                            ₹<Figure>{Number(r.value).toLocaleString('en-IN', { maximumFractionDigits: 2 })}</Figure>
                          </td>
                        </tr>
                      );
                    })}
                </tbody>
              </table>
            </div>

            {/* Pagination */}
            <div className="flex items-center justify-between text-caption text-ink-muted">
              <span>
                Showing {(gridPage - 1) * 15 + 1}–{Math.min(gridPage * 15, gridQuery.data!.rows.length)} of{' '}
                <Figure>{gridQuery.data!.rows.length.toLocaleString('en-IN')}</Figure> records
              </span>
              <div className="flex items-center gap-1.5">
                <button
                  type="button"
                  disabled={gridPage === 1}
                  onClick={() => setGridPage((p) => Math.max(1, p - 1))}
                  className="rounded border border-line px-2.5 py-1 disabled:opacity-40 hover:bg-surface-alt"
                >
                  Previous
                </button>
                <span className="px-2">
                  Page {gridPage} of {Math.ceil(gridQuery.data!.rows.length / 15)}
                </span>
                <button
                  type="button"
                  disabled={gridPage >= Math.ceil(gridQuery.data!.rows.length / 15)}
                  onClick={() => setGridPage((p) => p + 1)}
                  className="rounded border border-line px-2.5 py-1 disabled:opacity-40 hover:bg-surface-alt"
                >
                  Next
                </button>
              </div>
            </div>
          </div>
        )}
      </Card>

      <NarrativePanel
        view="price"
        onExport={() => onExport('Price dashboard narrative', undefined)}
      />
    </div>
  );
}
