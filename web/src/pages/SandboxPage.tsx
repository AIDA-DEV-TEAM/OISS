/**
 * Guided data-science sandbox — RFP areas 6 and 7.
 *
 * Crop-yield forecasting is a preset inside the sandbox rather than a separate
 * screen, which is how the demo flow describes it. Ten reversible steps:
 * Dataset → Use case → Target → Features → Split → Horizon → Run → Results →
 * Save version → Publish.
 *
 * Two honesty constraints from prompt 7 shape the wording here. The model is
 * fitted on a single year with no time dimension, so it estimates yield given
 * area rather than forecasting forward — the UI says "estimate", never
 * "forecast to 2027". And the pooled R² is flattered by separation between
 * crops, so the per-crop table sits beside it and no accuracy claim is made.
 */
import { useEffect, useState } from 'react';
import {
  Bar,
  BarChart,
  CartesianGrid,
  Legend,
  ResponsiveContainer,
  Scatter,
  ScatterChart,
  Tooltip,
  XAxis,
  YAxis,
  ZAxis,
} from 'recharts';

import type { SandboxRunStatus, SandboxVersion } from '@/api/contracts';
import {
  createRun,
  fetchRunStatus,
  usePublishVersion,
  useRunResults,
  useSandboxColumns,
  useSandboxDatasets,
  useSaveVersion,
  useUseCases,
} from '@/api/sandbox';
import { ExportModal } from '@/components/ExportModal';
import { PageHeader } from '@/components/PageHeader';
import { Card, Figure, StatCard, cn } from '@/components/primitives';
import { ProvenanceNote } from '@/components/ProvenanceNote';
import { ErrorState, LoadingState } from '@/components/states';
import { CHART_COLORS, CHART_INK } from '@/features/dashboard/constants';
import { RUN_STEP_COUNT } from '@/mocks/sandbox';
import { toExportContext } from '@/lib/exportContext';

const STEPS = [
  'Dataset',
  'Use case',
  'Target',
  'Features',
  'Train/test split',
  'Horizon',
  'Run',
  'Results',
  'Save version',
  'Publish',
] as const;

const SPLITS = ['70 / 30', '80 / 20', '90 / 10'] as const;

const HORIZONS = [
  {
    id: 'same_season',
    label: 'Same-season estimate',
    detail:
      'Estimate yield for the year the model was fitted on. The model has no time dimension, so this is the only horizon it supports.',
    enabled: true,
  },
  {
    id: 'one_year',
    label: 'One year ahead',
    detail: 'Requires a model fitted across multiple years. This one was fitted on 2024-25 alone.',
    enabled: false,
  },
  {
    id: 'three_year',
    label: 'Three years ahead',
    detail: 'Requires a model fitted across multiple years. This one was fitted on 2024-25 alone.',
    enabled: false,
  },
];

export function SandboxPage() {
  const [step, setStep] = useState(0);
  const [datasetId, setDatasetId] = useState<string | null>(null);
  const [useCaseId, setUseCaseId] = useState<string | null>(null);
  const [target, setTarget] = useState<string | null>(null);
  const [features, setFeatures] = useState<string[]>([]);
  const [split, setSplit] = useState<string>('80 / 20');
  const [horizon, setHorizon] = useState<string>('same_season');
  const [runId, setRunId] = useState<string | null>(null);
  const [status, setStatus] = useState<SandboxRunStatus | null>(null);
  const [runError, setRunError] = useState<unknown>(null);
  const [version, setVersion] = useState<SandboxVersion | null>(null);
  const [published, setPublished] = useState(false);
  const [exportOpen, setExportOpen] = useState(false);

  const datasets = useSandboxDatasets();
  const useCases = useUseCases();
  const columns = useSandboxColumns(datasetId ?? undefined);
  const results = useRunResults(status?.status === 'completed' ? runId ?? undefined : undefined);
  const saveVersion = useSaveVersion();
  const publish = usePublishVersion();

  // Default to the crop-yield preset, which is the scenario the RFP asks for.
  useEffect(() => {
    if (!useCaseId && useCases.data) {
      const preset = useCases.data.find((u) => u.is_default) ?? useCases.data[0];
      setUseCaseId(preset.id);
    }
  }, [useCases.data, useCaseId]);

  useEffect(() => {
    if (!datasetId && datasets.data) setDatasetId(datasets.data[0].dataset_id);
  }, [datasets.data, datasetId]);

  useEffect(() => {
    if (!target && columns.data) {
      const preset = columns.data.find((c) => c.role === 'target');
      if (preset) setTarget(preset.name);
    }
    if (features.length === 0 && columns.data) {
      setFeatures(columns.data.filter((c) => c.role === 'feature').map((c) => c.name));
    }
  }, [columns.data, target, features.length]);

  // The run is a job: poll status until it completes, exactly as the real
  // endpoint will behave once the work is no longer instant.
  useEffect(() => {
    if (!runId || !status || status.status === 'completed' || status.status === 'failed') return;
    let cancelled = false;
    const poll = window.setTimeout(() => {
      const next = Math.min(pollIndex(status), RUN_STEP_COUNT - 1);
      fetchRunStatus(runId, next)
        .then((s) => {
          if (!cancelled) setStatus(s);
        })
        .catch((error: unknown) => {
          if (!cancelled) setRunError(error);
        });
    }, 500);
    return () => {
      cancelled = true;
      window.clearTimeout(poll);
    };
  }, [runId, status]);

  async function startRun() {
    setRunError(null);
    setStep(6);
    try {
      const created = await createRun();
      setRunId(created.run_id);
      setStatus(await fetchRunStatus(created.run_id, 0));
    } catch (error) {
      setRunError(error);
    }
  }

  const canAdvance = stepIsComplete(step, {
    datasetId,
    useCaseId,
    target,
    features,
    status,
    version,
    published,
  });

  return (
    <>
      <PageHeader
        title="Data science sandbox"
        description="Configure a scenario, run it, inspect the results and publish them to the dashboard. The crop-yield estimator is the default preset."
      />

      <div className="space-y-4">
        <Stepper current={step} onSelect={setStep} maxReached={maxReachable(status, version, published)} />

        <Card title={STEPS[step]} description={STEP_HINT[step]}>
          {step === 0 && (
            <ChoiceList
              query={datasets}
              loadingLabel="Loading datasets"
              items={(datasets.data ?? []).map((d) => ({
                id: d.dataset_id,
                label: d.label,
                detail: `${d.grain} · ${d.years} · ${d.row_count.toLocaleString('en-IN')} rows`,
              }))}
              selected={datasetId}
              onSelect={setDatasetId}
            />
          )}

          {step === 1 && (
            <ChoiceList
              query={useCases}
              loadingLabel="Loading use cases"
              items={(useCases.data ?? []).map((u) => ({
                id: u.id,
                label: u.is_default ? `${u.label} (default)` : u.label,
                detail: u.description,
              }))}
              selected={useCaseId}
              onSelect={setUseCaseId}
            />
          )}

          {step === 2 && (
            <ChoiceList
              query={columns}
              loadingLabel="Loading columns"
              items={(columns.data ?? [])
                .filter((c) => c.role === 'target' || c.role === 'both')
                .map((c) => ({ id: c.name, label: c.label, detail: `${c.dtype} column` }))}
              selected={target}
              onSelect={setTarget}
            />
          )}

          {step === 3 && (
            <>
              {columns.isPending && <LoadingState label="Loading columns" rows={4} />}
              {columns.isError && (
                <ErrorState error={columns.error} onRetry={() => columns.refetch()} />
              )}
              {columns.data && (
                <ul className="space-y-2">
                  {columns.data
                    .filter((c) => c.name !== target && c.role !== 'identifier')
                    .map((column) => {
                      const checked = features.includes(column.name);
                      return (
                        <li key={column.name}>
                          <label className="flex cursor-pointer items-start gap-2">
                            <input
                              type="checkbox"
                              checked={checked}
                              className="mt-1"
                              onChange={() =>
                                setFeatures((prev) =>
                                  checked
                                    ? prev.filter((f) => f !== column.name)
                                    : [...prev, column.name],
                                )
                              }
                            />
                            <span>
                              <span className="block text-body text-ink">{column.label}</span>
                              <span className="block text-caption text-ink-muted">
                                {column.dtype} column
                              </span>
                            </span>
                          </label>
                        </li>
                      );
                    })}
                </ul>
              )}
            </>
          )}

          {step === 4 && (
            <ChoiceList
              items={SPLITS.map((s) => ({
                id: s,
                label: s,
                detail: `${s.split(' / ')[0]} per cent of rows used for fitting.`,
              }))}
              selected={split}
              onSelect={setSplit}
            />
          )}

          {step === 5 && (
            <ChoiceList
              items={HORIZONS.map((h) => ({
                id: h.id,
                label: h.label,
                detail: h.detail,
                disabled: !h.enabled,
              }))}
              selected={horizon}
              onSelect={setHorizon}
            />
          )}

          {step === 6 && (
            <RunStep status={status} error={runError} onStart={startRun} />
          )}

          {step === 7 && (
            <>
              {results.isPending && <LoadingState label="Loading results" rows={6} />}
              {results.isError && (
                <ErrorState error={results.error} onRetry={() => results.refetch()} />
              )}
              {results.data && (
                <ResultsStep results={results.data} onExport={() => setExportOpen(true)} />
              )}
            </>
          )}

          {step === 8 && (
            <SaveStep
              runId={runId}
              version={version}
              pending={saveVersion.isPending}
              error={saveVersion.error}
              parameters={{
                Dataset: datasets.data?.find((d) => d.dataset_id === datasetId)?.label ?? '—',
                'Use case': useCases.data?.find((u) => u.id === useCaseId)?.label ?? '—',
                Target: columns.data?.find((c) => c.name === target)?.label ?? '—',
                Features: features.length ? features.join(', ') : '—',
                Split: split,
                Horizon: HORIZONS.find((h) => h.id === horizon)?.label ?? '—',
              }}
              onSave={(label) => {
                if (!runId) return;
                saveVersion.mutate(
                  { runId, label },
                  { onSuccess: (saved) => setVersion(saved) },
                );
              }}
            />
          )}

          {step === 9 && (
            <PublishStep
              version={version}
              published={published}
              pending={publish.isPending}
              error={publish.error}
              onPublish={() => {
                if (!version) return;
                publish.mutate(version.version_id, { onSuccess: () => setPublished(true) });
              }}
            />
          )}
        </Card>

        <div className="flex items-center justify-between">
          <button
            type="button"
            disabled={step === 0}
            onClick={() => setStep((s) => Math.max(0, s - 1))}
            className="rounded border border-line bg-surface px-3 py-1.5 text-body text-ink-muted transition-colors duration-state hover:bg-surface-alt hover:text-ink disabled:opacity-40"
          >
            Back
          </button>
          <button
            type="button"
            disabled={!canAdvance || step === STEPS.length - 1}
            onClick={() => (step === 5 ? void startRun() : setStep((s) => s + 1))}
            className="rounded border border-primary bg-primary px-3 py-1.5 text-body font-medium text-surface transition-colors duration-state hover:bg-primary-hover disabled:opacity-40"
          >
            {step === 5 ? 'Run' : 'Continue'}
          </button>
        </div>
      </div>

      <ExportModal
        open={exportOpen}
        onClose={() => setExportOpen(false)}
        exportType="model_output"
        context={
          results.data
            ? toExportContext({
                panelTitle: 'Minor-crop yield estimates',
                period: '2024-25',
                rowCount: results.data.predictions.length,
                dataOrigin: results.data.data_origin,
              })
            : null
        }
      />
    </>
  );
}

const STEP_HINT: Record<number, string> = {
  0: 'Which loaded dataset the scenario reads.',
  1: 'The scenario preset. Crop-yield estimation is the default.',
  2: 'The column the model estimates.',
  3: 'The columns the model may use as inputs.',
  4: 'How rows are divided between fitting and held-out evaluation.',
  5: 'How far ahead the estimate reaches.',
  6: 'The run executes as a job and reports real progress.',
  7: 'Metrics, residuals, feature importance and the predictions themselves.',
  8: 'Store this run with its parameters so it can be reproduced.',
  9: 'Push the saved version to the dashboard panel.',
};

function pollIndex(status: SandboxRunStatus): number {
  // Progress maps onto the status sequence; the real endpoint reads the row.
  if (status.status === 'queued') return 1;
  if (status.progress < 46) return 2;
  if (status.progress < 78) return 3;
  if (status.progress < 94) return 4;
  return 5;
}

function maxReachable(
  status: SandboxRunStatus | null,
  version: SandboxVersion | null,
  published: boolean,
): number {
  if (published) return 9;
  if (version) return 9;
  if (status?.status === 'completed') return 8;
  if (status) return 6;
  return 5;
}

function stepIsComplete(
  step: number,
  state: {
    datasetId: string | null;
    useCaseId: string | null;
    target: string | null;
    features: string[];
    status: SandboxRunStatus | null;
    version: SandboxVersion | null;
    published: boolean;
  },
): boolean {
  switch (step) {
    case 0:
      return Boolean(state.datasetId);
    case 1:
      return Boolean(state.useCaseId);
    case 2:
      return Boolean(state.target);
    case 3:
      return state.features.length > 0;
    case 4:
    case 5:
      return true;
    case 6:
      return state.status?.status === 'completed';
    case 7:
      return true;
    case 8:
      return Boolean(state.version);
    default:
      return false;
  }
}

function Stepper({
  current,
  maxReached,
  onSelect,
}: {
  current: number;
  maxReached: number;
  onSelect: (step: number) => void;
}) {
  return (
    <nav aria-label="Sandbox steps">
      <ol className="flex flex-wrap gap-1.5">
        {STEPS.map((label, index) => {
          const reachable = index <= maxReached;
          const active = index === current;
          return (
            <li key={label}>
              <button
                type="button"
                disabled={!reachable}
                aria-current={active ? 'step' : undefined}
                onClick={() => onSelect(index)}
                title={reachable ? undefined : 'Complete the earlier steps first'}
                className={cn(
                  'rounded border px-2.5 py-1 text-caption transition-colors duration-state',
                  active
                    ? 'border-primary bg-primary-subtle font-medium text-primary'
                    : reachable
                      ? 'border-line bg-surface text-ink-muted hover:bg-surface-alt hover:text-ink'
                      : 'cursor-not-allowed border-line bg-surface-alt text-ink-subtle',
                )}
              >
                <Figure>{index + 1}</Figure>. {label}
              </button>
            </li>
          );
        })}
      </ol>
    </nav>
  );
}

interface ChoiceItem {
  id: string;
  label: string;
  detail: string;
  disabled?: boolean;
}

function ChoiceList({
  items,
  selected,
  onSelect,
  query,
  loadingLabel,
}: {
  items: ChoiceItem[];
  selected: string | null;
  onSelect: (id: string) => void;
  query?: { isPending: boolean; isError: boolean; error: unknown; refetch: () => void };
  loadingLabel?: string;
}) {
  if (query?.isPending) return <LoadingState label={loadingLabel ?? 'Loading'} rows={3} />;
  if (query?.isError) return <ErrorState error={query.error} onRetry={() => query.refetch()} />;

  return (
    <ul className="space-y-2">
      {items.map((item) => (
        <li key={item.id}>
          <label
            className={cn(
              'flex items-start gap-2 rounded border px-3 py-2 transition-colors duration-state',
              item.disabled
                ? 'cursor-not-allowed border-line bg-surface-alt opacity-60'
                : selected === item.id
                  ? 'cursor-pointer border-primary bg-primary-subtle'
                  : 'cursor-pointer border-line bg-surface hover:bg-surface-alt',
            )}
            title={item.disabled ? item.detail : undefined}
          >
            <input
              type="radio"
              name="sandbox-choice"
              className="mt-1"
              disabled={item.disabled}
              checked={selected === item.id}
              onChange={() => onSelect(item.id)}
            />
            <span className="min-w-0">
              <span className="block text-body font-medium text-ink">{item.label}</span>
              <span className="block text-caption text-ink-muted">{item.detail}</span>
            </span>
          </label>
        </li>
      ))}
    </ul>
  );
}

function RunStep({
  status,
  error,
  onStart,
}: {
  status: SandboxRunStatus | null;
  error: unknown;
  onStart: () => void;
}) {
  if (error) return <ErrorState error={error} onRetry={onStart} />;
  if (!status) {
    return (
      <div>
        <p className="text-body text-ink-muted">
          The run fans out one prediction call per district, crop and season, stores the
          results, and marks itself complete.
        </p>
        <button
          type="button"
          onClick={onStart}
          className="mt-3 rounded border border-primary bg-primary px-3 py-1.5 text-body font-medium text-surface transition-colors duration-state hover:bg-primary-hover"
        >
          Start run
        </button>
      </div>
    );
  }

  const done = status.status === 'completed';
  return (
    <div>
      <div className="flex items-baseline justify-between gap-3">
        <p className="text-body font-medium text-ink">{status.message}</p>
        <p className="text-caption text-ink-muted">
          <Figure>{status.progress}</Figure>%
        </p>
      </div>
      <div
        className="mt-2 h-2 w-full overflow-hidden rounded bg-surface-alt"
        role="progressbar"
        aria-valuenow={status.progress}
        aria-valuemin={0}
        aria-valuemax={100}
        aria-label="Run progress"
      >
        <div
          className={cn('h-full transition-all duration-state', done ? 'bg-success' : 'bg-primary')}
          // Width is the live progress value, so it cannot be a utility class.
          style={{ width: `${status.progress}%` }}
        />
      </div>
      <p className="mt-2 text-caption text-ink-subtle">
        Run <Figure>{status.run_id}</Figure> · status {status.status}
      </p>
    </div>
  );
}

function ResultsStep({
  results,
  onExport,
}: {
  results: NonNullable<ReturnType<typeof useRunResults>['data']>;
  onExport: () => void;
}) {
  const bounds = results.actual_vs_predicted.reduce(
    (acc, row) => ({
      min: Math.min(acc.min, row.actual, row.predicted),
      max: Math.max(acc.max, row.actual, row.predicted),
    }),
    { min: Infinity, max: -Infinity },
  );
  const identity = [
    { actual: bounds.min, predicted: bounds.min },
    { actual: bounds.max, predicted: bounds.max },
  ];

  return (
    <div className="space-y-4">
      <div className="flex items-start justify-between gap-3">
        <ProvenanceNote signals={{ dataOrigin: results.data_origin }} />
        <button
          type="button"
          onClick={onExport}
          className="shrink-0 rounded border border-line bg-surface px-2.5 py-1 text-caption font-medium text-ink-muted transition-colors duration-state hover:bg-surface-alt hover:text-ink"
        >
          Export
        </button>
      </div>

      <div className="grid grid-cols-1 gap-card sm:grid-cols-2 xl:grid-cols-4">
        <StatCard label="R² (pooled)" value={results.pooled.r2.toFixed(3)} />
        <StatCard label="RMSE" value={results.pooled.rmse.toFixed(2)} unit="qtl/ha" />
        <StatCard label="MAE" value={results.pooled.mae.toFixed(2)} unit="qtl/ha" />
        <StatCard label="Records scored" value={results.pooled.n.toLocaleString('en-IN')} />
      </div>

      <p className="text-caption text-ink-muted">
        The pooled figure is computed across all crops together, so it reflects the
        separation between crops as much as accuracy within one. The per-crop table
        below is the comparable view.
      </p>

      <div className="grid grid-cols-1 gap-card xl:grid-cols-2">
        <section>
          <h3 className="mb-2 text-section font-semibold text-ink">Metrics by crop</h3>
          <div className="overflow-x-auto rounded border border-line">
            <table className="w-full text-left text-body">
              <caption className="sr-only">Model metrics for each crop</caption>
              <thead className="border-b border-line bg-surface-alt text-caption font-medium uppercase tracking-header text-ink-subtle">
                <tr>
                  <th className="px-3 py-2">Crop</th>
                  <th className="px-3 py-2 text-right">R²</th>
                  <th className="px-3 py-2 text-right">RMSE</th>
                  <th className="px-3 py-2 text-right">MAE</th>
                  <th className="px-3 py-2 text-right">n</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-line bg-surface">
                {results.per_crop.map((row) => (
                  <tr key={row.crop_id} className="hover:bg-surface-alt">
                    <td className="px-3 py-2 text-ink">{row.crop_name}</td>
                    <td className="px-3 py-2 text-right text-ink">
                      <Figure>{row.r2.toFixed(3)}</Figure>
                    </td>
                    <td className="px-3 py-2 text-right text-ink">
                      <Figure>{row.rmse.toFixed(2)}</Figure>
                    </td>
                    <td className="px-3 py-2 text-right text-ink">
                      <Figure>{row.mae.toFixed(2)}</Figure>
                    </td>
                    <td className="px-3 py-2 text-right text-ink">
                      <Figure>{row.n}</Figure>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </section>

        <section>
          <h3 className="mb-2 text-section font-semibold text-ink">Actual against predicted</h3>
          <div className="h-80 rounded border border-line bg-surface p-card-chart">
            <ResponsiveContainer width="100%" height="100%">
              <ScatterChart margin={{ top: 8, right: 16, bottom: 32, left: 8 }}>
                <CartesianGrid stroke={CHART_INK.grid} />
                <XAxis
                  type="number"
                  dataKey="actual"
                  name="Actual"
                  tick={{ fontSize: 12, fill: CHART_INK.axis }}
                  label={{
                    value: 'Actual (qtl/ha)',
                    position: 'insideBottom',
                    offset: -16,
                    style: { fontSize: 12, fill: CHART_INK.axis },
                  }}
                />
                <YAxis
                  type="number"
                  dataKey="predicted"
                  name="Predicted"
                  tick={{ fontSize: 12, fill: CHART_INK.axis }}
                  label={{
                    value: 'Predicted (qtl/ha)',
                    angle: -90,
                    position: 'insideLeft',
                    style: { fontSize: 12, fill: CHART_INK.axis },
                  }}
                />
                <ZAxis range={[48, 48]} />
                <Tooltip contentStyle={{ fontSize: 12 }} cursor={{ strokeDasharray: '3 3' }} />
                <Legend wrapperStyle={{ fontSize: 12 }} />
                <Scatter
                  name="District / crop"
                  data={results.actual_vs_predicted}
                  fill={CHART_COLORS[0]}
                />
                <Scatter
                  name="Perfect agreement"
                  data={identity}
                  line={{ stroke: CHART_INK.reference, strokeWidth: 1 }}
                  shape={() => <g />}
                  legendType="line"
                />
              </ScatterChart>
            </ResponsiveContainer>
          </div>
        </section>
      </div>

      <section>
        <h3 className="mb-2 text-section font-semibold text-ink">What drove the estimate</h3>
        <div className="grid grid-cols-1 gap-card xl:grid-cols-3">
          <div className="h-64 rounded border border-line bg-surface p-card-chart xl:col-span-1">
            <ResponsiveContainer width="100%" height="100%">
              <BarChart
                data={results.feature_importance}
                layout="vertical"
                margin={{ top: 8, right: 16, bottom: 8, left: 8 }}
              >
                <CartesianGrid stroke={CHART_INK.grid} horizontal={false} />
                <XAxis type="number" tick={{ fontSize: 12, fill: CHART_INK.axis }} />
                <YAxis
                  type="category"
                  dataKey="label"
                  width={84}
                  tick={{ fontSize: 12, fill: CHART_INK.axis }}
                />
                <Tooltip
                  contentStyle={{ fontSize: 12 }}
                  formatter={(value: number | string) => Number(value).toFixed(3)}
                />
                <Bar dataKey="weight" name="Weight" fill={CHART_COLORS[0]} />
              </BarChart>
            </ResponsiveContainer>
          </div>
          <p className="text-body leading-relaxed text-ink xl:col-span-2">
            {results.explanation}
          </p>
        </div>
      </section>

      <section>
        <h3 className="mb-2 text-section font-semibold text-ink">Predictions</h3>
        <div className="max-h-panel overflow-auto rounded border border-line">
          <table className="w-full text-left text-body">
            <caption className="sr-only">Predicted yield and estimated production</caption>
            <thead className="sticky top-0 border-b border-line bg-surface-alt text-caption font-medium uppercase tracking-header text-ink-subtle">
              <tr>
                <th className="px-3 py-2">District</th>
                <th className="px-3 py-2">Crop</th>
                <th className="px-3 py-2">Season</th>
                <th className="px-3 py-2 text-right">Area (ha)</th>
                <th className="px-3 py-2 text-right">Yield (qtl/ha)</th>
                <th className="px-3 py-2 text-right">Production (qtl)</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-line bg-surface">
              {results.predictions.map((row) => (
                <tr key={`${row.district_id}-${row.crop_id}-${row.season}`} className="hover:bg-surface-alt">
                  <td className="px-3 py-2 text-ink">{row.district_name}</td>
                  <td className="px-3 py-2 text-ink">{row.crop_name}</td>
                  <td className="px-3 py-2 text-ink-muted">{row.season}</td>
                  <td className="px-3 py-2 text-right text-ink">
                    <Figure>{row.area_ha.toLocaleString('en-IN')}</Figure>
                  </td>
                  <td className="px-3 py-2 text-right text-ink">
                    <Figure>{row.predicted_yield_qtl_per_ha.toFixed(2)}</Figure>
                  </td>
                  <td className="px-3 py-2 text-right text-ink">
                    <Figure>{row.estimated_production_qtls.toLocaleString('en-IN')}</Figure>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </section>
    </div>
  );
}

function SaveStep({
  runId,
  version,
  parameters,
  pending,
  error,
  onSave,
}: {
  runId: string | null;
  version: SandboxVersion | null;
  parameters: Record<string, string>;
  pending: boolean;
  error: unknown;
  onSave: (label: string) => void;
}) {
  const [label, setLabel] = useState('Minor-crop yield, 2024-25');

  if (version) {
    return (
      <div className="rounded border border-success/30 bg-success-bg px-card py-4">
        <p className="text-body font-medium text-success">Version saved</p>
        <p className="mt-1 text-body text-ink">
          <Figure>{version.version_id}</Figure> — {version.label}
        </p>
        <dl className="mt-3 grid grid-cols-1 gap-x-gutter gap-y-2 sm:grid-cols-2">
          {Object.entries(version.parameters).map(([term, value]) => (
            <div key={term}>
              <dt className="text-caption font-medium text-ink-muted">{term}</dt>
              <dd className="text-body text-ink">{value}</dd>
            </div>
          ))}
        </dl>
      </div>
    );
  }

  return (
    <div>
      <dl className="grid grid-cols-1 gap-x-gutter gap-y-2 sm:grid-cols-2">
        {Object.entries(parameters).map(([term, value]) => (
          <div key={term}>
            <dt className="text-caption font-medium text-ink-muted">{term}</dt>
            <dd className="text-body text-ink">{value}</dd>
          </div>
        ))}
      </dl>
      <label className="mt-4 block">
        <span className="block text-caption font-medium text-ink-muted">Version label</span>
        <input
          type="text"
          value={label}
          onChange={(event) => setLabel(event.target.value)}
          className="mt-1 w-full max-w-md rounded border border-line bg-surface px-3 py-1.5 text-body text-ink"
        />
      </label>
      {error !== null && error !== undefined && (
        <div className="mt-3">
          <ErrorState error={error} compact />
        </div>
      )}
      <button
        type="button"
        disabled={!runId || pending}
        onClick={() => onSave(label)}
        className="mt-3 rounded border border-primary bg-primary px-3 py-1.5 text-body font-medium text-surface transition-colors duration-state hover:bg-primary-hover disabled:opacity-40"
      >
        {pending ? 'Saving…' : 'Save version'}
      </button>
    </div>
  );
}

function PublishStep({
  version,
  published,
  pending,
  error,
  onPublish,
}: {
  version: SandboxVersion | null;
  published: boolean;
  pending: boolean;
  error: unknown;
  onPublish: () => void;
}) {
  if (published) {
    return (
      <div className="rounded border border-success/30 bg-success-bg px-card py-4">
        <p className="text-body font-medium text-success">Published to the dashboard</p>
        <p className="mt-1 text-body text-ink">
          The agriculture dashboard's actual-against-estimate panel now reads from version{' '}
          <Figure>{version?.version_id}</Figure>.
        </p>
      </div>
    );
  }

  return (
    <div>
      <p className="text-body text-ink-muted">
        Publishing writes the estimates to the dashboard panel and records a lineage edge
        from the run through the version to the published rows. Every published row carries
        the analytical-estimate label.
      </p>
      {error !== null && error !== undefined && (
        <div className="mt-3">
          <ErrorState error={error} compact />
        </div>
      )}
      <button
        type="button"
        disabled={!version || pending}
        onClick={onPublish}
        className="mt-3 rounded border border-primary bg-primary px-3 py-1.5 text-body font-medium text-surface transition-colors duration-state hover:bg-primary-hover disabled:opacity-40"
      >
        {pending ? 'Publishing…' : 'Publish to dashboard'}
      </button>
    </div>
  );
}
