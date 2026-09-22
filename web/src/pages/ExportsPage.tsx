/**
 * Exports — RFP area 8.
 *
 * Lists what has been produced, with the context each file carries, so an
 * evaluator can see that an export is defensible rather than just downloadable.
 * Selecting a row opens its full context: filters, period, dataset versions,
 * origin mix and caveats.
 */
import { useState } from 'react';

import type { ExportRecord } from '@/api/contracts';
import { useRecentExports } from '@/api/exports';
import { DataTable } from '@/components/DataTable';
import type { Column } from '@/components/DataTable';
import { Drawer } from '@/components/Drawer';
import { PageHeader } from '@/components/PageHeader';
import { Badge, Card, DefinitionList, Figure } from '@/components/primitives';
import { CaveatList } from '@/components/provenance';
import { ProvenanceNote } from '@/components/ProvenanceNote';
import { AsyncPanel } from '@/components/states';
import { formatBytes, formatTimestamp } from '@/lib/format';

const FORMAT_LABEL: Record<string, string> = {
  csv: 'CSV',
  xlsx: 'Excel',
  pdf: 'PDF',
  json: 'JSON',
  png: 'Chart image',
};

const TYPE_LABEL: Record<string, string> = {
  dashboard_panel: 'Dashboard panel',
  records_grid: 'Records grid',
  assistant_answer: 'Assistant answer',
  model_output: 'Model output',
  narrative: 'Narrative',
};

export function ExportsPage() {
  const exports = useRecentExports();
  const [selected, setSelected] = useState<ExportRecord | null>(null);

  const columns: Array<Column<ExportRecord>> = [
    {
      key: 'file',
      header: 'File',
      render: (row) => (
        <div className="min-w-0">
          <span className="block truncate font-medium text-ink">{row.filename}</span>
          <span className="block truncate text-caption text-ink-subtle">
            {row.context.panel_title}
          </span>
        </div>
      ),
    },
    {
      key: 'format',
      header: 'Format',
      width: '120px',
      render: (row) => <Badge tone="neutral">{FORMAT_LABEL[row.format] ?? row.format}</Badge>,
    },
    {
      key: 'type',
      header: 'Source',
      width: '150px',
      render: (row) => (
        <span className="text-ink-muted">{TYPE_LABEL[row.export_type] ?? row.export_type}</span>
      ),
    },
    {
      key: 'rows',
      header: 'Rows',
      numeric: true,
      width: '90px',
      render: (row) => <Figure>{row.context.row_count.toLocaleString('en-IN')}</Figure>,
    },
    {
      key: 'size',
      header: 'Size',
      numeric: true,
      width: '100px',
      render: (row) => <Figure>{formatBytes(row.size_bytes)}</Figure>,
    },
    {
      key: 'created',
      header: 'Created',
      width: '170px',
      render: (row) => (
        <Figure className="text-ink-muted">{formatTimestamp(row.created_at)}</Figure>
      ),
    },
    {
      key: 'download',
      header: 'Download',
      width: '120px',
      render: () => (
        <button
          type="button"
          onClick={(event) => event.stopPropagation()}
          className="rounded border border-line bg-surface px-2.5 py-1 text-caption font-medium text-primary transition-colors duration-state hover:bg-primary-subtle"
        >
          Download
        </button>
      ),
    },
  ];

  return (
    <>
      <PageHeader
        title="Exports"
        description="Files produced from dashboards, assistant answers, records grids and model runs. Each carries the filters, period, dataset versions and caveats that produced it."
      />

      <AsyncPanel
        query={exports}
        loadingLabel="Loading exports"
        loadingRows={6}
        empty={{
          title: 'No exports yet',
          detail:
            'Use the export control on any dashboard panel, assistant answer or model result. Completed files are listed here with their context.',
        }}
      >
        {(rows) => (
          <Card
            title="Recent exports"
            description="Select a row to see the full context attached to that file."
            bodyClassName="p-0"
          >
            <DataTable
              columns={columns}
              rows={rows}
              rowKey={(row) => row.export_id}
              onRowActivate={setSelected}
              isRowSelected={(row) => row.export_id === selected?.export_id}
              caption="Recent exports with format, row count and size"
            />
          </Card>
        )}
      </AsyncPanel>

      <Drawer
        open={Boolean(selected)}
        title={selected?.filename ?? ''}
        description="Export context"
        onClose={() => setSelected(null)}
      >
        {selected && (
          <div className="space-y-4">
            <ProvenanceNote
              signals={{
                dataOrigin: selected.context.data_origin,
                grainSource: selected.context.grain_source,
              }}
            />

            <Card title="Export">
              <DefinitionList
                items={[
                  { term: 'Reference', value: <Figure>{selected.export_id}</Figure> },
                  { term: 'Format', value: FORMAT_LABEL[selected.format] ?? selected.format },
                  {
                    term: 'Source',
                    value: TYPE_LABEL[selected.export_type] ?? selected.export_type,
                  },
                  { term: 'Size', value: <Figure>{formatBytes(selected.size_bytes)}</Figure> },
                  {
                    term: 'Created',
                    value: <Figure>{formatTimestamp(selected.created_at)}</Figure>,
                  },
                  { term: 'Status', value: selected.status },
                ]}
              />
            </Card>

            <Card title="Applied context" description="Travels inside the file, not only on screen.">
              <DefinitionList
                items={[
                  { term: 'Panel', value: selected.context.panel_title, wide: true },
                  {
                    term: 'Rows',
                    value: <Figure>{selected.context.row_count.toLocaleString('en-IN')}</Figure>,
                  },
                  { term: 'Period', value: selected.context.period ?? '—' },
                  {
                    term: 'Filters',
                    value:
                      selected.context.filters.length === 0
                        ? 'None'
                        : selected.context.filters
                            .map((f) => `${f.dimension}: ${f.values.join(', ')}`)
                            .join(' · '),
                    wide: true,
                  },
                  {
                    term: 'Source datasets',
                    value:
                      selected.context.source_datasets.length === 0 ? (
                        'None'
                      ) : (
                        <ul className="space-y-0.5">
                          {selected.context.source_datasets.map((source) => (
                            <li key={source.dataset_version_id}>
                              <code className="text-caption">{source.dataset_version_id}</code>
                            </li>
                          ))}
                        </ul>
                      ),
                    wide: true,
                  },
                ]}
              />
            </Card>

            {selected.context.caveats.length > 0 && (
              <Card title="Caveats" description="Recorded in the file alongside the rows.">
                <CaveatList caveats={selected.context.caveats} />
              </Card>
            )}
          </div>
        )}
      </Drawer>
    </>
  );
}
