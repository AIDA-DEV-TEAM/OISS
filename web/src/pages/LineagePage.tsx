/**
 * Storage and lineage — RFP area 2.
 *
 * One dataset at a time: its layer journey, its version record, its validation
 * summary, and the lineage graph from source file through the layers to the
 * analytics tables and exports.
 *
 * The 2022-23 paddy rollup appears in the graph as its own `aggregate` hop,
 * because district paddy for that year was never published at district grain —
 * it was summed from block records, and a reviewer will ask.
 */
import { useEffect, useMemo, useState } from 'react';

import type { DatasetVersion } from '@/api/client';
import {
  useDataset,
  useDatasets,
  useLayers,
  useLineage,
  useValidationSummary,
} from '@/api/hooks';
import { AppliedContextStrip } from '@/components/AppliedContextStrip';
import { DataTable } from '@/components/DataTable';
import type { Column } from '@/components/DataTable';
import { Drawer } from '@/components/Drawer';
import { PageHeader } from '@/components/PageHeader';
import { Badge, Card, DefinitionList, Figure, SeverityChip } from '@/components/primitives';
import type { Severity } from '@/components/primitives';
import { ProvenanceNote } from '@/components/ProvenanceNote';
import { AsyncPanel, EmptyState, ErrorState, LoadingState } from '@/components/states';
import { LayerFlow } from '@/features/lineage/LayerFlow';
import { LineageGraph } from '@/features/lineage/LineageGraph';
import { fileName, formatCount, formatTimestamp, humanRule, shortHash } from '@/lib/format';

/** Maps a graph node back to the dataset version it belongs to, when it is one. */
function nodeDatasetName(node: string): string | null {
  const match = /^(?:raw|staging)\.(.+)$/.exec(node);
  if (match) return match[1];
  if (node.startsWith('file:') || node.startsWith('upload:')) return null;
  return null;
}

export function LineagePage() {
  const datasets = useDatasets();
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [selectedNode, setSelectedNode] = useState<string | null>(null);

  const sourceDatasets = useMemo(
    () => (datasets.data?.items ?? []).filter((d) => d.layer !== 'reference'),
    [datasets.data],
  );

  useEffect(() => {
    if (!selectedId && sourceDatasets.length > 0) {
      // Default to the 2022-23 paddy dataset: it is the one carrying the block
      // rollup, which is what a reviewer usually asks about first.
      const rollup = sourceDatasets.find(
        (d) => d.dataset_name === 'earas_2022_23_block_paddy',
      );
      setSelectedId((rollup ?? sourceDatasets[0]).dataset_version_id);
    }
  }, [sourceDatasets, selectedId]);

  const selected = sourceDatasets.find((d) => d.dataset_version_id === selectedId);
  const layers = useLayers(selectedId ?? undefined);
  const lineage = useLineage(selectedId ?? undefined);
  const summary = useValidationSummary(selectedId ?? undefined);

  const nodeVersion = useDataset(
    selectedNode ? (selectedNode.startsWith('file:') ? undefined : selectedId ?? undefined) : undefined,
  );

  const hasRollup = (lineage.data?.edges ?? []).some(
    (edge) => edge.edge_type === 'aggregate',
  );

  const datasetColumns: Array<Column<DatasetVersion>> = [
    {
      key: 'name',
      header: 'Dataset',
      render: (dataset) => (
        <span className="font-medium text-ink">{dataset.dataset_name}</span>
      ),
    },
    {
      key: 'rows',
      header: 'Rows',
      numeric: true,
      width: '100px',
      render: (dataset) => <Figure>{formatCount(dataset.row_count)}</Figure>,
    },
    {
      key: 'sha',
      header: 'Checksum',
      width: '150px',
      render: (dataset) => (
        <code className="text-caption text-ink-muted" title={dataset.sha256}>
          {shortHash(dataset.sha256)}
        </code>
      ),
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
    <>
      <PageHeader
        title="Storage and lineage"
        description="Where each figure came from: the file, the layers it passed through, and the tables it reached."
      />

      <div className="space-y-4">
        <AsyncPanel
          query={datasets}
          loadingLabel="Loading datasets"
          loadingRows={5}
          empty={{
            title: 'No datasets loaded',
            detail:
              'The backend has no dataset versions. Run `python -m app.cli build` to load the bundled data.',
          }}
        >
          {() => (
            <Card
              title="Dataset versions"
              description="Select a version to see its layers, its validation summary and its lineage."
              bodyClassName="p-0"
            >
              <DataTable
                columns={datasetColumns}
                rows={sourceDatasets}
                rowKey={(dataset) => dataset.dataset_version_id}
                onRowActivate={(dataset) => {
                  setSelectedId(dataset.dataset_version_id);
                  setSelectedNode(null);
                }}
                isRowSelected={(dataset) => dataset.dataset_version_id === selectedId}
                maxHeight="300px"
                caption="Dataset versions with row counts and checksums"
              />
            </Card>
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
                    Source file
                  </span>
                  <span className="truncate text-body text-ink" title={selected.source_file}>
                    {fileName(selected.source_file)}
                  </span>
                </div>
              }
            />

            {layers.isPending && <LoadingState label="Loading layer counts" rows={2} />}
            {layers.isError && (
              <ErrorState error={layers.error} onRetry={() => layers.refetch()} />
            )}
            {layers.data && <LayerFlow stages={layers.data.items} />}

            <div className="grid grid-cols-1 gap-4 xl:grid-cols-3">
              <Card title="Version record" className="xl:col-span-2">
                <DefinitionList
                  items={[
                    { term: 'Dataset name', value: selected.dataset_name },
                    {
                      term: 'Version id',
                      value: <code className="text-caption">{selected.dataset_version_id}</code>,
                    },
                    { term: 'Source type', value: selected.source_type },
                    {
                      term: 'Rows read',
                      value: <Figure>{formatCount(selected.row_count)}</Figure>,
                    },
                    {
                      term: 'Loaded at',
                      value: <Figure>{formatTimestamp(selected.loaded_at)}</Figure>,
                    },
                    {
                      term: 'SHA-256',
                      value: (
                        <code className="break-all text-caption" title={selected.sha256}>
                          {selected.sha256}
                        </code>
                      ),
                      wide: true,
                    },
                  ]}
                />
              </Card>

              <Card title="Validation summary" description="Findings recorded for this version.">
                {summary.isPending && <LoadingState label="Loading summary" rows={3} />}
                {summary.isError && (
                  <ErrorState error={summary.error} onRetry={() => summary.refetch()} compact />
                )}
                {summary.data &&
                  (summary.data.items.length === 0 ? (
                    <EmptyState
                      title="No findings"
                      detail="No rule produced a finding against this dataset version."
                    />
                  ) : (
                    <ul className="space-y-2">
                      {summary.data.items.map((rule) => (
                        <li
                          key={rule.rule_code}
                          className="flex items-center justify-between gap-3"
                        >
                          <span className="min-w-0 truncate text-body text-ink">
                            {humanRule(rule.rule_code)}
                          </span>
                          <SeverityChip
                            severity={rule.severity as Severity}
                            count={rule.finding_count}
                          />
                        </li>
                      ))}
                    </ul>
                  ))}
              </Card>
            </div>

            <Card
              title="Lineage"
              description="Source file → raw → staging → analytics → export. Select a node to see its version record."
              note={
                <ProvenanceNote
                  className="mt-0.5"
                  signals={{
                    grainSource: hasRollup ? 'aggregated_from_blocks' : 'published_district',
                  }}
                />
              }
            >
              {lineage.isPending && <LoadingState label="Loading lineage" rows={3} />}
              {lineage.isError && (
                <ErrorState error={lineage.error} onRetry={() => lineage.refetch()} />
              )}
              {lineage.data &&
                (lineage.data.edges.length === 0 ? (
                  <EmptyState
                    title="No lineage recorded"
                    detail="This version has no lineage edges. Reference tables are loaded directly and carry a single reference edge."
                  />
                ) : (
                  <>
                    <LineageGraph
                      edges={lineage.data.edges}
                      selectedNode={selectedNode}
                      onSelectNode={setSelectedNode}
                    />
                    {hasRollup && (
                      <p className="mt-3 border-l-rule border-l-aggregated bg-aggregated-bg px-3 py-2 text-caption text-ink-muted">
                        The <strong className="font-medium">aggregate</strong> hop is how
                        district paddy exists for 2022-23: DE&amp;S published that year
                        block-wise only, so block rows were summed to district grain and
                        the yield recomputed as total production over total area.
                      </p>
                    )}
                  </>
                ))}
            </Card>
          </>
        )}
      </div>

      <Drawer
        open={Boolean(selectedNode)}
        title={selectedNode ?? ''}
        description="Lineage node"
        onClose={() => setSelectedNode(null)}
      >
        {selectedNode && (
          <div className="space-y-4">
            <Card title="Node">
              <DefinitionList
                items={[
                  { term: 'Node', value: <code className="break-all text-caption">{selectedNode}</code>, wide: true },
                  {
                    term: 'Belongs to dataset',
                    value: nodeDatasetName(selectedNode) ?? selected?.dataset_name ?? '—',
                  },
                ]}
              />
            </Card>

            {selected && (
              <Card title="Dataset version">
                {nodeVersion.isPending ? (
                  <LoadingState label="Loading version" rows={3} />
                ) : nodeVersion.isError ? (
                  <ErrorState error={nodeVersion.error} compact />
                ) : nodeVersion.data ? (
                  <DefinitionList
                    items={[
                      { term: 'Version id', value: <code className="text-caption">{nodeVersion.data.dataset_version_id}</code>, wide: true },
                      { term: 'Rows read', value: <Figure>{formatCount(nodeVersion.data.row_count)}</Figure> },
                      { term: 'Layer', value: <Badge tone="neutral">{nodeVersion.data.layer}</Badge> },
                      { term: 'Loaded at', value: <Figure>{formatTimestamp(nodeVersion.data.loaded_at)}</Figure> },
                      {
                        term: 'SHA-256',
                        value: <code className="break-all text-caption">{nodeVersion.data.sha256}</code>,
                        wide: true,
                      },
                      {
                        term: 'Source file',
                        value: <span title={nodeVersion.data.source_file}>{fileName(nodeVersion.data.source_file)}</span>,
                        wide: true,
                      },
                    ]}
                  />
                ) : null}
              </Card>
            )}
          </div>
        )}
      </Drawer>
    </>
  );
}
