import {
  Bar,
  BarChart,
  CartesianGrid,
  Line,
  LineChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from 'recharts';

import type { ChartSpec } from '@/api/client';
import { CHART_COLORS, CHART_INK } from '@/features/dashboard/constants';

interface AnswerChartProps {
  spec: ChartSpec;
}

const AXIS_TICK = { fontSize: 12, fill: CHART_INK.axis };

export function AnswerChart({ spec }: AnswerChartProps) {
  const yLabel = {
    value: spec.unit,
    angle: -90,
    position: 'insideLeft' as const,
    style: { fontSize: 12, fill: CHART_INK.axis },
  };

  return (
    <figure className="mt-4">
      <figcaption className="sr-only">
        {spec.series_label} ({spec.unit}) by {spec.x_key.replaceAll('_', ' ')}
      </figcaption>
      <div className="h-72">
        <ResponsiveContainer width="100%" height="100%">
          {spec.kind === 'bar' ? (
            <BarChart data={spec.data} margin={{ top: 8, right: 16, bottom: 56, left: 8 }}>
              <CartesianGrid stroke={CHART_INK.grid} vertical={false} />
              <XAxis
                dataKey={spec.x_key}
                angle={-35}
                textAnchor="end"
                interval={0}
                height={56}
                tick={AXIS_TICK}
              />
              <YAxis tick={AXIS_TICK} label={yLabel} />
              <Tooltip contentStyle={{ fontSize: 12 }} />
              <Bar dataKey={spec.y_key} name={spec.series_label} fill={CHART_COLORS[0]} />
            </BarChart>
          ) : (
            <LineChart data={spec.data} margin={{ top: 8, right: 16, bottom: 32, left: 8 }}>
              <CartesianGrid stroke={CHART_INK.grid} vertical={false} />
              <XAxis dataKey={spec.x_key} tick={AXIS_TICK} />
              <YAxis tick={AXIS_TICK} label={yLabel} />
              <Tooltip contentStyle={{ fontSize: 12 }} />
              <Line
                type="monotone"
                dataKey={spec.y_key}
                name={spec.series_label}
                stroke={CHART_COLORS[0]}
                strokeWidth={2}
                dot={{ r: 3 }}
                connectNulls={false}
              />
            </LineChart>
          )}
        </ResponsiveContainer>
      </div>
    </figure>
  );
}
