/**
 * Actual versus published model forecast — RFP areas 6 and 7 surfacing on the
 * dashboard.
 *
 * Stays empty until the sandbox publishes a version, and says so rather than
 * disappearing. Where 2024-25 actuals have not been published for a pairing the
 * bar is absent, never zero (DESIGN.md §6).
 */
import {
  Bar,
  BarChart,
  CartesianGrid,
  Legend,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from 'recharts';

import { useDashboardForecasts } from '@/api/forecasts';
import { Card, Figure } from '@/components/primitives';
import { ProvenanceNote } from '@/components/ProvenanceNote';
import { EmptyState, ErrorState, LoadingState } from '@/components/states';
import { CHART_COLORS, CHART_INK } from '@/features/dashboard/constants';

export function ActualVsForecastPanel({ onExport }: { onExport?: () => void }) {
  const forecasts = useDashboardForecasts();

  const rows = (forecasts.data ?? []).map((f) => ({
    label: `${f.district_name} · ${f.crop_name}`,
    actual: f.actual_yield,
    forecast: f.forecast_yield,
    unit: f.unit,
  }));

  const origin = forecasts.data?.[0]?.data_origin ?? { model: 1 };
  const withoutActual = rows.filter((r) => r.actual === null).length;

  return (
    <Card
      title="Actual against model estimate"
      description="Published sandbox results compared with harvested actuals, by district and crop."
      chart
      actions={
        onExport && (
          <button
            type="button"
            onClick={onExport}
            className="rounded border border-line bg-surface px-2.5 py-1 text-caption font-medium text-ink-muted transition-colors duration-state hover:bg-surface-alt hover:text-ink"
          >
            Export
          </button>
        )
      }
    >
      {forecasts.isPending && <LoadingState label="Loading published forecasts" rows={5} />}
      {forecasts.isError && (
        <ErrorState error={forecasts.error} onRetry={() => forecasts.refetch()} />
      )}
      {forecasts.data && rows.length === 0 && (
        <EmptyState
          title="No model version published yet"
          detail="Run the crop-yield scenario in the sandbox and publish a version. Its estimates appear here alongside the harvested actuals."
        />
      )}
      {forecasts.data && rows.length > 0 && (
        <>
          <ProvenanceNote className="mb-2" signals={{ dataOrigin: origin }} />
          <div className="h-96">
            <ResponsiveContainer width="100%" height="100%">
              <BarChart data={rows} margin={{ top: 8, right: 16, bottom: 88, left: 8 }}>
                <CartesianGrid stroke={CHART_INK.grid} vertical={false} />
                <XAxis
                  dataKey="label"
                  angle={-45}
                  textAnchor="end"
                  interval={0}
                  height={88}
                  tick={{ fontSize: 12, fill: CHART_INK.axis }}
                />
                <YAxis
                  tick={{ fontSize: 12, fill: CHART_INK.axis }}
                  label={{
                    value: 'Yield (qtl/ha)',
                    angle: -90,
                    position: 'insideLeft',
                    style: { fontSize: 12, fill: CHART_INK.axis },
                  }}
                />
                <Tooltip
                  contentStyle={{ fontSize: 12 }}
                  formatter={(value: number | string, name: string) => [
                    `${Number(value).toFixed(2)} qtl/ha`,
                    name,
                  ]}
                />
                <Legend wrapperStyle={{ fontSize: 12 }} />
                <Bar dataKey="actual" name="Actual (harvested)" fill={CHART_COLORS[0]} />
                <Bar dataKey="forecast" name="Model estimate" fill={CHART_COLORS[1]} />
              </BarChart>
            </ResponsiveContainer>
          </div>
          {withoutActual > 0 && (
            <p className="mt-2 text-caption text-ink-muted">
              <Figure>{withoutActual}</Figure> of{' '}
              <Figure>{rows.length}</Figure> pairings have no published 2024-25 actual
              yet. Those bars are absent rather than drawn at zero.
            </p>
          )}
        </>
      )}
    </Card>
  );
}
