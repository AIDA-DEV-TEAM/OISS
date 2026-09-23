/**
 * Guided data-science sandbox — RFP areas 6 and 7.
 *
 * The model is pre-trained and served by a separate service, so the wizard
 * offers only real choices: Dataset → Use case → Model configuration → Run →
 * Results → Save version → Publish. The use case and the model configuration
 * are read-only: they are what the model service states, each field labelled
 * with the endpoint that stated it, and "not stated" where it states nothing.
 *
 * Honesty constraints shape the wording. The service does not state its
 * training period, so the estimates may include the year they are compared
 * against: they are "model estimates vs published actuals", never a forecast.
 * And the pooled R² is flattered by separation between crops, so the per-crop
 * table sits beside it and no accuracy claim is made.
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

import type {
  ModelConfig,
  SandboxDataset,
  SandboxModelConfig,
  SandboxRunStatus,
  SandboxVersion,
  StatedText,
} from '@/api/client';
import {
  createRun,
  useModelConfig,
  usePublishVersion,
  useRunResults,
  useSandboxDatasets,
  useSaveVersion,
} from '@/api/sandbox';
import { ExportModal } from '@/components/ExportModal';
import { PageHeader } from '@/components/PageHeader';
import { Card, Figure, StatCard, cn } from '@/components/primitives';
import { ProvenanceNote } from '@/components/ProvenanceNote';
import { ErrorState, LoadingState } from '@/components/states';
import { CHART_COLORS, CHART_INK } from '@/features/dashboard/constants';
import { toExportContext } from '@/lib/exportContext';

const STEPS = [
  'Dataset',
  'Use case',
  'Model configuration',
  'Run',
  'Results',
  'Save version',
  'Publish',
] as const;

const RUN_STEP = 3;
const RESULTS_STEP = 4;

const NOT_STATED = 'not stated by the model service';

export function SandboxPage() {
  const [step, setStep] = useState(0);
  const [datasetId, setDatasetId] = useState<string | null>(null);
  const [running, setRunning] = useState(false);
  const [status, setStatus] = useState<SandboxRunStatus | null>(null);
  const [runError, setRunError] = useState<unknown>(null);
  const [version, setVersion] = useState<SandboxVersion | null>(null);
  const [published, setPublished] = useState(false);
  const [exportOpen, setExportOpen] = useState(false);

  const datasets = useSandboxDatasets();
  const modelConfig = useModelConfig();
  const runId = status?.run_id;
  const results = useRunResults(hasResults(status) ? runId : undefined);
  const saveVersion = useSaveVersion();
  const publish = usePublishVersion();

  // Start on the first dataset the model can run over; never on one it cannot.
  useEffect(() => {
    if (!datasetId && datasets.data) {
      const first = datasets.data.items.find((d) => d.compatible === true);
      if (first) setDatasetId(first.dataset_id);
    }
  }, [datasets.data, datasetId]);

  async function startRun() {
    if (!datasetId) return;
    setRunError(null);
    setStatus(null);
    setVersion(null);
    setPublished(false);
    setStep(RUN_STEP);
    setRunning(true);
    try {
      // The request returns when the run has ended; there is no job to poll.
      setStatus(await createRun({ dataset_id: datasetId, use_case: 'minor_crop_yield' }));
    } catch (error) {
      setRunError(error);
    } finally {
      setRunning(false);
    }
  }

  const canAdvance = stepIsComplete(step, {
    datasetId,
    modelConfig: modelConfig.data,
    status,
    version,
  });
  const selectedDataset = datasets.data?.items.find((d) => d.dataset_id === datasetId);
  const years = results.data?.agri_years.join(' / ') ?? '';

  return (
    <>
      <PageHeader
        title="Data science sandbox"
        description="Run the pre-trained crop-yield model over a loaded dataset, inspect the estimates against published actuals, and publish them to the dashboard."
      />

      <div className="space-y-4">
        <Stepper current={step} onSelect={setStep} maxReached={maxReachable(status, version, published)} />

        <Card title={STEPS[step]} description={STEP_HINT[step]}>
          {step === 0 && (
            <DatasetStep query={datasets} selected={datasetId} onSelect={setDatasetId} />
          )}

          {step === 1 && (
            <UseCaseStep query={modelConfig} />
          )}

          {step === 2 && (
            <ModelConfigStep query={modelConfig} />
          )}

          {step === RUN_STEP && (
            <RunStep running={running} status={status} error={runError} onStart={startRun} />
          )}

          {step === RESULTS_STEP && (
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

          {step === 5 && (
            <SaveStep
              runId={runId ?? null}
              version={version}
              pending={saveVersion.isPending}
              error={saveVersion.error}
              parameters={{
                Dataset: selectedDataset?.label ?? '—',
                'Use case': modelConfig.data?.use_case.label ?? '—',
                ...configTerms(results.data?.model_configuration ?? null),
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

          {step === 6 && (
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
            disabled={step === 0 || running}
            onClick={() => setStep((s) => Math.max(0, s - 1))}
            className="rounded border border-line bg-surface px-3 py-1.5 text-body text-ink-muted transition-colors duration-state hover:bg-surface-alt hover:text-ink disabled:opacity-40"
          >
            Back
          </button>
          <button
            type="button"
            disabled={!canAdvance || running || step === STEPS.length - 1}
            onClick={() => (step === RUN_STEP - 1 ? void startRun() : setStep((s) => s + 1))}
            className="rounded border border-primary bg-primary px-3 py-1.5 text-body font-medium text-surface transition-colors duration-state hover:bg-primary-hover disabled:opacity-40"
          >
            {step === RUN_STEP - 1 ? 'Run' : 'Continue'}
          </button>
        </div>
      </div>

      <ExportModal
        open={exportOpen}
        onClose={() => setExportOpen(false)}
        exportType="model_output"
        panel={
          results.data
            ? {
                title: 'Minor-crop yield estimates',
                spec: {
                  metric: 'predicted_yield',
                  dimensions: ['district', 'crop', 'season'],
                  filters: [
                    { dimension: 'run_id', op: 'in', values: [results.data.run_id] },
                  ],
                  // The export service re-runs this without its display limit.
                  limit: 1000,
                  include_records: false,
                },
                rows: results.data.predictions as unknown as Array<Record<string, unknown>>,
                context: toExportContext({
                  panelTitle: 'Minor-crop yield estimates',
                  period: years,
                  rowCount: results.data.predictions.length,
                  dataOrigin: results.data.data_origin,
                }),
              }
            : null
        }
      />
    </>
  );
}

const STEP_HINT: Record<number, string> = {
  0: 'Which loaded dataset the model runs over. Each is checked against the fields the model requires and the values it accepts.',
  1: 'What the model estimates. Fixed: the model service exposes one model with one target.',
  2: 'The model as the model service states it. Nothing here is set by this system.',
  3: 'Calls the model service for each district, crop and season; this can take a minute.',
  4: 'The estimates beside published actuals, and the model service’s own evaluation of its model.',
  5: 'Store this run with the model configuration it ran against, so it can be reproduced.',
  6: 'Push the saved version to the dashboard panel.',
};

/** What a failed run's code means, as a heading above its message. */
const FAILURE_HEADINGS: Record<string, string> = {
  MODEL_SERVICE_UNAVAILABLE: 'The model service is unavailable',
  MODEL_SERVICE_REJECTED: 'The model service rejected a request',
  MODEL_SERVICE_ERROR: 'The model service returned an error',
  MALFORMED_RESPONSE: 'The model service sent a response that could not be read',
  DATASET_INCOMPATIBLE: 'This dataset cannot supply the model’s inputs',
  NO_INPUTS_IN_DOMAIN: 'No combination falls within the model’s input domains',
  STORAGE_FAILED: 'The results could not be stored',
};

/** R² to three places, or a dash when it could not be computed. */
function formatR2(r2: number | null | undefined): string {
  return r2 === null || r2 === undefined ? '—' : r2.toFixed(3);
}

/** A metric to two places, or a dash when there was nothing to compute it from. */
function formatMetric(value: number | null | undefined): string {
  return value === null || value === undefined ? '—' : value.toFixed(2);
}

/** Completed, with or without warnings: either way every estimate is stored. */
function hasResults(status: SandboxRunStatus | null | undefined): boolean {
  return status?.status === 'completed' || status?.status === 'completed_with_warnings';
}

/** A stated value, or the plain fact that the service does not state it. */
function stated(field: StatedText | null | undefined): string {
  return field?.value ?? NOT_STATED;
}

/** The model configuration as a version's terms, for the save step. */
function configTerms(config: ModelConfig | null): Record<string, string> {
  if (!config) return { 'Model configuration': 'not recorded for this run' };
  return {
    Model: stated(config.model_name),
    Target: stated(config.target),
    Features: config.features.value.map((f) => f.name).join(', '),
    'Model version': stated(config.model_version),
    'Training period': stated(config.training_period),
  };
}

function maxReachable(
  status: SandboxRunStatus | null,
  version: SandboxVersion | null,
  published: boolean,
): number {
  if (published || version) return 6;
  if (hasResults(status)) return 5;
  if (status) return RUN_STEP;
  return 2;
}

function stepIsComplete(
  step: number,
  state: {
    datasetId: string | null;
    modelConfig: SandboxModelConfig | undefined;
    status: SandboxRunStatus | null;
    version: SandboxVersion | null;
  },
): boolean {
  switch (step) {
    case 0:
      return Boolean(state.datasetId);
    case 1:
    case 2:
      // Read-only steps: complete once the service has been asked, whatever it said.
      return Boolean(state.modelConfig) && Boolean(state.datasetId);
    case RUN_STEP:
      return hasResults(state.status);
    case RESULTS_STEP:
      return true;
    case 5:
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

function DatasetStep({
  query,
  selected,
  onSelect,
}: {
  query: ReturnType<typeof useSandboxDatasets>;
  selected: string | null;
  onSelect: (id: string) => void;
}) {
  const listing = query.data;
  return (
    <div className="space-y-3">
      {listing && !listing.model_checked && (
        <p
          role="status"
          className="rounded border-l-rule border-l-warning bg-warning-bg px-3 py-2 text-caption text-ink"
        >
          {listing.message} A run can still replay an earlier run of the same dataset, and
          says so.
        </p>
      )}
      <ChoiceList
        query={query}
        loadingLabel="Loading datasets"
        items={(listing?.items ?? []).map((d) => ({
          id: d.dataset_id,
          label: d.label,
          detail: datasetDetail(d),
          // Unchecked is not incompatible: without the service neither is known.
          disabled: d.compatible === false,
        }))}
        selected={selected}
        onSelect={onSelect}
      />
    </div>
  );
}

/** A dataset's size, and what it can or cannot give the model, and why. */
function datasetDetail(dataset: SandboxDataset): string {
  const size = `${dataset.years} · ${dataset.row_count.toLocaleString('en-IN')} rows in this system`;
  if (dataset.compatible === null || dataset.compatible === undefined) {
    return `${size} · compatibility not checked`;
  }
  if (dataset.missing_fields.length > 0) {
    const missing = dataset.missing_fields.map((m) => `${m.field} (${m.reason})`).join('; ');
    return `${size} · cannot run: missing ${missing}`;
  }
  const summary = dataset.input_summary;
  if (!summary) return size;
  const out = summary.out_of_domain.map((o) => `${o.count} ${o.reason}`).join('; ');
  const sent = `${summary.sent} of ${summary.combinations} district × crop × season combinations within the model's input domains`;
  if (summary.sent === 0) return `${size} · cannot run: none of its combinations are within the model's input domains (${out})`;
  return out ? `${size} · ${sent}; not sent: ${out}` : `${size} · ${sent}`;
}

function UseCaseStep({ query }: { query: ReturnType<typeof useModelConfig> }) {
  if (query.isPending) return <LoadingState label="Asking the model service" rows={2} />;
  if (query.isError) return <ErrorState error={query.error} onRetry={() => query.refetch()} />;
  const useCase = query.data.use_case;
  return (
    <div className="rounded border border-line bg-surface-alt px-3 py-2">
      <p className="text-body font-medium text-ink">{useCase.label}</p>
      <p className="mt-0.5 text-caption text-ink-muted">{useCase.description}</p>
      <p className="mt-2 text-caption text-ink-muted">{useCase.fixed_reason}</p>
    </div>
  );
}

function ModelConfigStep({ query }: { query: ReturnType<typeof useModelConfig> }) {
  if (query.isPending) return <LoadingState label="Asking the model service" rows={4} />;
  if (query.isError) return <ErrorState error={query.error} onRetry={() => query.refetch()} />;
  const { config, message } = query.data;
  if (!config) {
    return (
      <p
        role="status"
        className="rounded border-l-rule border-l-warning bg-warning-bg px-3 py-2 text-caption text-ink"
      >
        {message} A run will replay an earlier run of the same dataset if one exists, and show
        that run&apos;s stored configuration.
      </p>
    );
  }
  return <ConfigDetails config={config} configHash={query.data.config_hash ?? null} />;
}

/** Every field of a model configuration beside the endpoint that stated it. */
function ConfigDetails({ config, configHash }: { config: ModelConfig; configHash: string | null }) {
  const domains = config.input_domains.value;
  const area = domains.area_ha_range as { min?: number; max?: number } | undefined;
  const list = (key: string): string[] =>
    Array.isArray(domains[key]) ? (domains[key] as unknown[]).map(String) : [];

  return (
    <div className="space-y-4">
      <dl className="grid grid-cols-1 gap-x-gutter gap-y-3 sm:grid-cols-2">
        <StatedTerm term="Model" field={config.model_name} />
        <StatedTerm term="Target" field={config.target} />
        <StatedTerm term="Model version" field={config.model_version} />
        <StatedTerm term="Training period" field={config.training_period} />
      </dl>

      <section>
        <h3 className="text-section font-semibold text-ink">Features</h3>
        <p className="text-caption text-ink-subtle">Stated by {config.features.source}</p>
        <ul className="mt-1 space-y-1">
          {config.features.value.map((feature) => (
            <li key={feature.name} className="text-body text-ink">
              <Figure>{feature.name}</Figure>{' '}
              <span className="text-caption text-ink-muted">
                ({feature.type}) {feature.description}
              </span>
            </li>
          ))}
        </ul>
      </section>

      <section>
        <h3 className="text-section font-semibold text-ink">Input domains</h3>
        <p className="text-caption text-ink-subtle">
          Stated by {config.input_domains.source}. The values the model accepts, not features:
          combinations outside them are counted and not sent.
        </p>
        <dl className="mt-1 grid grid-cols-1 gap-x-gutter gap-y-2 sm:grid-cols-2">
          <DomainTerm term="Districts" values={list('districts')} />
          <DomainTerm term="Seasons" values={list('seasons')} />
          <DomainTerm term="Minor crops" values={list('minor_crops')} />
          <div>
            <dt className="text-caption font-medium text-ink-muted">Area (ha)</dt>
            <dd className="text-body text-ink">
              {area?.min !== undefined && area.max !== undefined ? (
                <>
                  <Figure>{area.min.toLocaleString('en-IN')}</Figure> to{' '}
                  <Figure>{area.max.toLocaleString('en-IN')}</Figure>
                </>
              ) : (
                NOT_STATED
              )}
            </dd>
          </div>
        </dl>
      </section>

      <p className="text-caption text-ink-subtle">
        Read from {config.service_url} at {config.fetched_at}
        {configHash ? (
          <>
            {' '}· configuration sha256 <Figure>{configHash.slice(0, 12)}</Figure>
          </>
        ) : null}
      </p>
    </div>
  );
}

function StatedTerm({ term, field }: { term: string; field: StatedText }) {
  return (
    <div>
      <dt className="text-caption font-medium text-ink-muted">{term}</dt>
      <dd className={cn('text-body', field.value ? 'text-ink' : 'text-ink-muted')}>
        {field.value ?? NOT_STATED}
      </dd>
      {field.source && <dd className="text-caption text-ink-subtle">Stated by {field.source}</dd>}
    </div>
  );
}

function DomainTerm({ term, values }: { term: string; values: string[] }) {
  return (
    <div>
      <dt className="text-caption font-medium text-ink-muted">
        {term} (<Figure>{values.length}</Figure>)
      </dt>
      <dd className="text-caption text-ink">{values.length ? values.join(', ') : NOT_STATED}</dd>
    </div>
  );
}

function RunStep({
  running,
  status,
  error,
  onStart,
}: {
  running: boolean;
  status: SandboxRunStatus | null;
  error: unknown;
  onStart: () => void;
}) {
  if (error) return <ErrorState error={error} onRetry={onStart} />;
  if (running) {
    return (
      <p role="status" className="text-body text-ink-muted">
        Calling the model service for each district, crop and season; this can take a minute.
      </p>
    );
  }
  if (!status) {
    return (
      <div>
        <p className="text-body text-ink-muted">
          The run reads the model&apos;s configuration, sends one prediction request per district,
          crop and season within the model&apos;s input domains, stores the estimates, then asks
          the service for its own evaluation of the model.
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

  const warned = status.status === 'completed_with_warnings';
  const failed = status.status === 'failed';
  return (
    <div
      role={failed ? 'alert' : warned ? 'status' : undefined}
      className={cn(
        'rounded border-l-rule px-3 py-2',
        failed ? 'border-l-error bg-error-bg' : warned ? 'border-l-warning bg-warning-bg' : 'border-l-success bg-success-bg',
      )}
    >
      {failed && (
        <p className="text-body font-medium text-error">
          {FAILURE_HEADINGS[status.error_code ?? ''] ?? 'The run failed'}
        </p>
      )}
      <p className={cn('text-body', failed ? 'text-ink' : warned ? 'font-medium text-warning' : 'font-medium text-ink')}>
        {status.message}
      </p>
      <p className="mt-2 text-caption text-ink-subtle">
        Run <Figure>{status.run_id}</Figure> · status {status.status}
        {status.error_code ? ` · ${status.error_code}` : ''}
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

      {results.warnings.length > 0 && (
        <div
          role="status"
          className="rounded border-l-rule border-l-warning bg-warning-bg px-3 py-2 text-caption text-ink"
        >
          <p className="font-medium text-warning">
            Every estimate is stored, but part of the model's evaluation could not be produced
          </p>
          <ul className="mt-1 list-disc space-y-0.5 pl-4 text-ink-muted">
            {results.warnings.map((warning) => (
              <li key={warning}>{warning}</li>
            ))}
          </ul>
        </div>
      )}

      {results.served_from_cache && (
        <p
          role="status"
          className="rounded border-l-rule border-l-warning bg-warning-bg px-3 py-2 text-caption text-ink-muted"
        >
          The model service was unavailable, so these are the stored results of run{' '}
          <Figure>{results.replayed_from ?? 'unknown'}</Figure>
          {results.replayed_run_at ? <>, made {results.replayed_run_at}</> : null}.{' '}
          {results.model_checked
            ? 'It ran the same model configuration over the same dataset.'
            : 'Current model could not be checked: service unavailable.'}{' '}
          Nothing here was estimated for this run.
        </p>
      )}

      <section>
        <h3 className="mb-2 text-section font-semibold text-ink">
          {results.served_from_cache ? 'Model configuration of the replayed run' : 'Model configuration'}
        </h3>
        {results.model_configuration ? (
          <ConfigDetails
            config={results.model_configuration}
            configHash={results.model_config_hash ?? null}
          />
        ) : (
          <p className="text-caption text-ink-muted">Not recorded for this run.</p>
        )}
      </section>

      <section>
        <h3 className="mb-2 text-section font-semibold text-ink">{results.comparison_label}</h3>
        <PredictionsTable results={results} />
      </section>

      <h3 className="text-section font-semibold text-ink">
        The model service&apos;s evaluation of its model
      </h3>
      <p className="text-caption text-ink-muted">
        Reported by the model service (GET /actual-vs-predicted, GET /feature-importance). These
        describe the model on the service&apos;s own test records, not the estimates above.
      </p>

      <div className="grid grid-cols-1 gap-card sm:grid-cols-2 xl:grid-cols-4">
        <StatCard label="R² (pooled)" value={formatR2(results.pooled?.r2)} />
        <StatCard label="RMSE" value={formatMetric(results.pooled?.rmse)} unit="qtl/ha" />
        <StatCard label="MAE" value={formatMetric(results.pooled?.mae)} unit="qtl/ha" />
        <StatCard
          label="Records scored"
          value={results.pooled ? results.pooled.n.toLocaleString('en-IN') : '—'}
        />
      </div>

      <p className="text-caption text-ink-muted">
        The pooled figure is computed across all crops together, so it reflects the
        separation between crops as much as accuracy within one. The per-crop table
        below is the comparable view.
      </p>

      <div className="grid grid-cols-1 gap-card xl:grid-cols-2">
        <section>
          <h3 className="mb-2 text-section font-semibold text-ink">Metrics by crop</h3>
          {results.per_crop.length === 0 ? (
            <EvaluationUnavailable />
          ) : (
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
                      <Figure>{formatR2(row.r2)}</Figure>
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
          )}
        </section>

        <section>
          <h3 className="mb-2 text-section font-semibold text-ink">Actual against predicted</h3>
          {results.actual_vs_predicted.length === 0 ? (
            <EvaluationUnavailable />
          ) : (
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
          )}
        </section>
      </div>

      <section>
        <h3 className="mb-2 text-section font-semibold text-ink">What drove the estimate</h3>
        {results.feature_importance.length === 0 ? (
          <EvaluationUnavailable />
        ) : (
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
        )}
      </section>
    </div>
  );
}

/** Each estimate beside the actual DE&S published for the same year. */
function PredictionsTable({
  results,
}: {
  results: NonNullable<ReturnType<typeof useRunResults>['data']>;
}) {
  const years = results.agri_years.join(' / ');
  return (
    <>
      <p className="mb-2 text-caption text-ink-muted">
        Each estimate beside the {years} yield DE&amp;S published for the same district, crop
        and season, read from this system&apos;s own database.
      </p>
      <div className="max-h-panel overflow-auto rounded border border-line">
        <table className="w-full text-left text-body">
          <caption className="sr-only">Estimated yield and the published actual</caption>
          <thead className="sticky top-0 border-b border-line bg-surface-alt text-caption font-medium uppercase tracking-header text-ink-subtle">
            <tr>
              <th className="px-3 py-2">District</th>
              <th className="px-3 py-2">Crop</th>
              <th className="px-3 py-2">Season</th>
              <th className="px-3 py-2 text-right">Area (ha)</th>
              <th className="px-3 py-2 text-right">Estimated yield (qtl/ha)</th>
              <th className="px-3 py-2 text-right">{years} actual (qtl/ha)</th>
              <th className="px-3 py-2 text-right">Production (qtl)</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-line bg-surface">
            {results.predictions.map((row) => (
              <tr
                key={`${row.district_id}-${row.crop_id}-${row.season}-${row.agri_year}`}
                className="hover:bg-surface-alt"
              >
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
                  {row.actual_yield_qtl_per_ha === null || row.actual_yield_qtl_per_ha === undefined ? (
                    <span
                      className="text-ink-subtle"
                      title={`No ${row.agri_year} yield published for this combination`}
                    >
                      —
                    </span>
                  ) : (
                    <Figure>{row.actual_yield_qtl_per_ha.toFixed(2)}</Figure>
                  )}
                </td>
                <td className="px-3 py-2 text-right text-ink">
                  <Figure>{row.estimated_production_qtls.toLocaleString('en-IN')}</Figure>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </>
  );
}

/** A section of the model's evaluation the service did not supply. */
function EvaluationUnavailable() {
  return (
    <p className="rounded border border-dashed border-line-strong bg-surface-alt px-3 py-4 text-caption text-ink-muted">
      Unavailable for this run. The warning above says which request failed and why; nothing
      is shown in its place.
    </p>
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
  const [label, setLabel] = useState('Minor-crop yield estimates');

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
