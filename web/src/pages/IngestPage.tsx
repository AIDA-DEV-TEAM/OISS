/**
 * Ingest and validate — RFP area 1.
 *
 * Two ways in: upload a file, or pick one of the bundled datasets the backend
 * already loaded. Both end in the same validation, quarantine and metadata
 * panels, because the backend runs the same code path for both.
 */
import { useEffect, useMemo, useState } from 'react';

import type { IngestResult, RuleSummary, ValidationFinding } from '@/api/client';
import { useDatasets, useIngestSchemas, useUpload, useValidationSummary } from '@/api/hooks';
import { AppliedContextStrip } from '@/components/AppliedContextStrip';
import { DataTable } from '@/components/DataTable';
import type { Column } from '@/components/DataTable';
import { PageHeader } from '@/components/PageHeader';
import { Badge, Card, Figure, StatCard, cn } from '@/components/primitives';
import { CaveatList } from '@/components/provenance';
import { AsyncPanel, ErrorState, LoadingState } from '@/components/states';
import { DatasetMetadata } from '@/features/ingest/DatasetMetadata';
import { QuarantinePanel } from '@/features/ingest/QuarantinePanel';
import { SchemaPreview } from '@/features/ingest/SchemaPreview';
import { ValidationFindings } from '@/features/ingest/ValidationFindings';
import { UploadPanel } from '@/features/ingest/UploadPanel';
import { fileName, formatCount, formatTimestamp } from '@/lib/format';
import { matchSchema } from '@/lib/matchSchema';
import type { SchemaMatch } from '@/lib/matchSchema';
import { parseFile } from '@/lib/parseFile';
import type { ParsedFile } from '@/lib/parseFile';
import type { DatasetVersion } from '@/api/client';

type Mode = 'bundled' | 'upload';

/** Upload findings_by_rule to the same shape the stored summary endpoint returns. */
function toSummary(result: IngestResult): RuleSummary[] {
  return result.findings_by_rule.map((entry) => ({
    rule_code: entry.rule_code,
    severity: entry.severity,
    finding_count: entry.count,
    sample_row_ref: null,
    sample_message: null,
    column_count: 0,
  }));
}

function ModeTab({
  active,
  onClick,
  children,
}: {
  active: boolean;
  onClick: () => void;
  children: React.ReactNode;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      aria-pressed={active}
      className={cn(
        'rounded border px-3 py-1.5 text-body transition-colors duration-state',
        active
          ? 'border-primary bg-primary-subtle font-medium text-primary'
          : 'border-line bg-surface text-ink-muted hover:bg-surface-alt hover:text-ink',
      )}
    >
      {children}
    </button>
  );
}

function BundledPicker({
  datasets,
  selectedId,
  onSelect,
}: {
  datasets: DatasetVersion[];
  selectedId: string | null;
  onSelect: (id: string) => void;
}) {
  const columns: Array<Column<DatasetVersion>> = [
    {
      key: 'name',
      header: 'Dataset',
      render: (dataset) => (
        <span className="font-medium text-ink">{dataset.dataset_name}</span>
      ),
    },
    {
      key: 'file',
      header: 'Source file',
      render: (dataset) => (
        <span className="text-ink-muted" title={dataset.source_file}>
          {fileName(dataset.source_file)}
        </span>
      ),
    },
    {
      key: 'type',
      header: 'Type',
      width: '90px',
      render: (dataset) => <Badge tone="neutral">{dataset.source_type}</Badge>,
    },
    {
      key: 'rows',
      header: 'Rows',
      numeric: true,
      width: '110px',
      render: (dataset) => <Figure>{formatCount(dataset.row_count)}</Figure>,
    },
    {
      key: 'loaded',
      header: 'Loaded',
      width: '170px',
      render: (dataset) => (
        <Figure className="text-ink-muted">{formatTimestamp(dataset.loaded_at)}</Figure>
      ),
    },
  ];

  return (
    <Card
      title="Bundled datasets"
      description="Loaded by the batch build. Select one to see its stored findings through the same panels an upload uses."
      bodyClassName="p-0"
    >
      <DataTable
        columns={columns}
        rows={datasets}
        rowKey={(dataset) => dataset.dataset_version_id}
        onRowActivate={(dataset) => onSelect(dataset.dataset_version_id)}
        isRowSelected={(dataset) => dataset.dataset_version_id === selectedId}
        maxHeight="330px"
        caption="Bundled datasets loaded by the batch build"
      />
    </Card>
  );
}

export function IngestPage() {
  const [mode, setMode] = useState<Mode>('bundled');
  const [selectedId, setSelectedId] = useState<string | null>(null);

  const [file, setFile] = useState<File | null>(null);
  const [parsed, setParsed] = useState<ParsedFile | null>(null);
  const [parseError, setParseError] = useState<Error | null>(null);
  const [datasetName, setDatasetName] = useState('');
  const [result, setResult] = useState<IngestResult | null>(null);
  const [schemaMatch, setSchemaMatch] = useState<SchemaMatch | null>(null);

  const datasets = useDatasets();
  const schemas = useIngestSchemas();
  const upload = useUpload();

  const sourceDatasets = useMemo(
    () => (datasets.data?.items ?? []).filter((d) => d.layer !== 'reference'),
    [datasets.data],
  );

  // Select the first dataset once, so the bundled view is never empty on
  // arrival. The upload target is deliberately NOT defaulted here: it is
  // derived from the uploaded file's own header once one is parsed, because
  // defaulting it to whichever dataset sorted first sent a price CSV to the
  // block land-use schema and its Stata reader.
  useEffect(() => {
    if (!selectedId && sourceDatasets.length > 0) {
      setSelectedId(sourceDatasets[0].dataset_version_id);
    }
  }, [sourceDatasets, selectedId]);

  // The file's columns pick the target. Below the match threshold nothing is
  // chosen, and the panel says so rather than guessing.
  useEffect(() => {
    if (!parsed || !schemas.data) return;
    const match = matchSchema(
      parsed.columns.map((column) => column.name),
      schemas.data.items,
    );
    setSchemaMatch(match);
    setDatasetName(match ? match.schema.dataset_name : '');
  }, [parsed, schemas.data]);

  const selected = sourceDatasets.find((d) => d.dataset_version_id === selectedId);
  const storedSummary = useValidationSummary(
    mode === 'bundled' ? selectedId ?? undefined : undefined,
  );

  async function handleFile(chosen: File) {
    setFile(chosen);
    setResult(null);
    setParseError(null);
    setParsed(null);
    try {
      setParsed(await parseFile(chosen));
    } catch (error) {
      setParseError(error instanceof Error ? error : new Error(String(error)));
    }
  }

  async function handleUpload() {
    if (!file || !parsed) return;
    // The backend readers take CSV and Stata, so a workbook is flattened to CSV
    // first. The conversion is stated next to the checksum rather than hidden.
    const payload = parsed.convertedFromSheet
      ? new Blob([parsed.csvText], { type: 'text/csv' })
      : file;
    const name = parsed.convertedFromSheet
      ? `${file.name.replace(/\.(xlsx|xls|xlsm)$/i, '')}.csv`
      : file.name;
    const response = await upload.mutateAsync({
      datasetName,
      file: payload,
      filename: name,
    });
    setResult(response);
  }

  const uploadFindings = (result?.findings ?? []) as ValidationFinding[];

  return (
    <>
      <PageHeader
        title="Ingest and validate"
        description="Every file, bundled or uploaded, goes through the same readers, the same rules and the same quarantine. Findings below are produced by that one code path."
        actions={
          <div className="flex items-center gap-2">
            <ModeTab active={mode === 'bundled'} onClick={() => setMode('bundled')}>
              Use a bundled dataset
            </ModeTab>
            <ModeTab active={mode === 'upload'} onClick={() => setMode('upload')}>
              Upload a file
            </ModeTab>
          </div>
        }
      />

      {datasets.isError && (
        <ErrorState error={datasets.error} onRetry={() => datasets.refetch()} />
      )}

      {mode === 'bundled' ? (
        <div className="space-y-4">
          <AsyncPanel
            query={datasets}
            loadingLabel="Loading datasets"
            loadingRows={6}
            empty={{
              title: 'No datasets loaded',
              detail:
                'The backend has no dataset versions. Run `python -m app.cli build` to load the bundled data.',
            }}
          >
            {(page) => (
              <BundledPicker
                datasets={page.items.filter((d) => d.layer !== 'reference')}
                selectedId={selectedId}
                onSelect={setSelectedId}
              />
            )}
          </AsyncPanel>

          {selected && (
            <>
              <AppliedContextStrip
                sources={[
                  {
                    dataset_name: selected.dataset_name,
                    dataset_version_id: selected.dataset_version_id,
                  },
                ]}
                rowCount={selected.row_count}
                extra={
                  <div className="flex min-w-0 flex-col gap-0.5">
                    <span className="text-caption font-medium uppercase tracking-header text-ink-subtle">
                      Load run
                    </span>
                    <span className="truncate text-body text-ink">
                      <Figure>{formatTimestamp(selected.loaded_at)}</Figure>
                    </span>
                  </div>
                }
              />

              <DatasetMetadata dataset={selected} />

              {storedSummary.isPending && (
                <LoadingState label="Loading validation summary" rows={5} />
              )}
              {storedSummary.isError && (
                <ErrorState
                  error={storedSummary.error}
                  onRetry={() => storedSummary.refetch()}
                />
              )}
              {storedSummary.data && (
                <ValidationFindings
                  summary={storedSummary.data.items}
                  versionId={selected.dataset_version_id}
                />
              )}

              <QuarantinePanel findings={[]} rowsQuarantined={0} />
            </>
          )}
        </div>
      ) : (
        <div className="space-y-4">
          <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
            <UploadPanel
              schemas={schemas.data?.items ?? []}
              datasetName={datasetName}
              match={schemaMatch}
              parsed={Boolean(parsed)}
              onDatasetNameChange={setDatasetName}
              onFile={handleFile}
              file={file}
              busy={upload.isPending}
            />

            <Card title="Ingestion status">
              {!file && (
                <p className="text-body text-ink-muted">
                  Choose a file to see its detected schema before anything is sent.
                </p>
              )}
              {file && parsed && (
                <div className="space-y-3">
                  <div className="grid grid-cols-2 gap-3">
                    <StatCard label="Columns" value={formatCount(parsed.columns.length)} />
                    <StatCard label="Data rows" value={formatCount(parsed.rowCount)} />
                  </div>
                  {parsed.convertedFromSheet && (
                    <p className="rounded border-l-rule border-l-warning bg-warning-bg px-3 py-2 text-caption text-ink-muted">
                      The backend readers accept CSV and Stata. Sheet “
                      {parsed.convertedFromSheet}” will be flattened to CSV before upload,
                      so the recorded checksum is of the converted data, not of the
                      original workbook.
                    </p>
                  )}
                  <button
                    type="button"
                    onClick={() => void handleUpload()}
                    disabled={upload.isPending || !datasetName}
                    className="w-full rounded border border-primary bg-primary px-3 py-2 text-body font-medium text-white transition-colors duration-state hover:bg-primary-hover disabled:cursor-not-allowed disabled:opacity-60"
                  >
                    {upload.isPending
                      ? 'Validating…'
                      : `Validate and ingest as ${datasetName}`}
                  </button>
                </div>
              )}
              {file && !parsed && !parseError && (
                <LoadingState label="Reading the file" rows={2} />
              )}
              {parseError && <ErrorState error={parseError} />}
              {upload.isError && (
                <div className="mt-3">
                  <ErrorState error={upload.error} />
                </div>
              )}
            </Card>
          </div>

          {parsed && <SchemaPreview parsed={parsed} />}

          {result && (
            <>
              <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
                <StatCard label="Rows read" value={formatCount(result.rows_read)} />
                <StatCard label="Rows staged" value={formatCount(result.rows_staged)} />
                <StatCard
                  label="Rows quarantined"
                  value={formatCount(result.rows_quarantined)}
                  badge={
                    result.rows_quarantined > 0 ? (
                      <Badge tone="error">Held back</Badge>
                    ) : (
                      <Badge tone="success">Clean</Badge>
                    )
                  }
                />
                <StatCard
                  label="Errors · warnings"
                  value={`${formatCount(result.error_count)} · ${formatCount(result.warning_count)}`}
                  hint={`${formatCount(result.info_count)} informational`}
                />
              </div>

              <Card title="Ingestion result" description="What the backend recorded for this upload.">
                <CaveatList
                  caveats={[]}
                  emptyLabel="No caveats apply to an ingestion run; caveats accompany query results."
                />
                <dl className="mt-3 grid grid-cols-1 gap-x-gutter gap-y-3 sm:grid-cols-2 xl:grid-cols-3">
                  <div>
                    <dt className="text-caption font-medium text-ink-muted">Version id</dt>
                    <dd className="mt-0.5 break-words text-body">
                      <code className="text-caption">{result.dataset_version_id}</code>
                    </dd>
                  </div>
                  <div>
                    <dt className="text-caption font-medium text-ink-muted">Run id</dt>
                    <dd className="mt-0.5 break-words text-body">
                      <code className="text-caption">{result.run_id}</code>
                    </dd>
                  </div>
                  <div>
                    <dt className="text-caption font-medium text-ink-muted">
                      Validated as
                    </dt>
                    <dd className="mt-0.5 text-body">{result.dataset_name}</dd>
                  </div>
                  <div>
                    <dt className="text-caption font-medium text-ink-muted">File</dt>
                    <dd className="mt-0.5 break-words text-body">{result.filename}</dd>
                  </div>
                  <div>
                    <dt className="text-caption font-medium text-ink-muted">Data origin</dt>
                    <dd className="mt-0.5 text-body">{result.data_origin}</dd>
                  </div>
                </dl>
              </Card>

              <ValidationFindings
                summary={toSummary(result)}
                localFindings={uploadFindings}
                localCapped
              />

              <QuarantinePanel
                findings={uploadFindings}
                quarantineTable={result.quarantine_table}
                rowsQuarantined={result.rows_quarantined}
              />
            </>
          )}
        </div>
      )}
    </>
  );
}
