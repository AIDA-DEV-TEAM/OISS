import { useMemo, useState } from 'react';
import { useQuery } from '@tanstack/react-query';

import { api, type QuerySpec } from '@/api/client';
import { Drawer } from '@/components/Drawer';
import { Figure } from '@/components/primitives';
import { EmptyState, ErrorState, LoadingState } from '@/components/states';

export interface DrillDownDrawerProps {
  spec?: QuerySpec | null;
  querySpec?: QuerySpec | null;
  open?: boolean;
  title?: string;
  onClose: () => void;
}

export function DrillDownDrawer(props: DrillDownDrawerProps) {
  const spec = props.querySpec !== undefined ? props.querySpec : (props.spec ?? null);
  const isOpen = props.open !== undefined ? props.open : Boolean(spec);
  const title = props.title || 'Supporting fact rows';
  const { onClose } = props;
  const [filterText, setFilterText] = useState('');

  const { data, isLoading, error, refetch } = useQuery({
    queryKey: ['drill-down-records', spec],
    queryFn: () => (spec ? api.records(spec) : null),
    enabled: Boolean(spec && isOpen),
  });

  const records = useMemo(() => {
    const raw = (data?.records || []) as Array<Record<string, unknown>>;
    if (!filterText.trim()) return raw;
    const q = filterText.toLowerCase();
    return raw.filter((r) =>
      Object.values(r).some((v) => v !== null && v !== undefined && String(v).toLowerCase().includes(q)),
    );
  }, [data, filterText]);

  const sources = data?.source_datasets || [];

  return (
    <Drawer
      open={isOpen && Boolean(spec)}
      title={title}
      description={
        spec && (
          <div className="flex flex-col gap-0.5">
            <span>
              Query metric: <span className="font-medium text-ink">{spec.metric}</span>
              {data && (
                <>
                  {' '}· <Figure>{data.total_matching.toLocaleString('en-IN')}</Figure> fact rows
                  {data.truncated && ' (showing top 500)'}
                </>
              )}
            </span>
            {sources.length > 0 && (
              <span className="truncate text-ink-subtle" title={sources.map((s) => s.dataset_name).join(', ')}>
                Source: {sources.map((s) => s.dataset_name).join(', ')}
              </span>
            )}
          </div>
        )
      }
      onClose={onClose}
    >
      {isLoading && <LoadingState label="Fetching supporting fact rows from DuckDB..." />}

      {error && (
        <ErrorState
          error={error}
          onRetry={() => void refetch()}
        />
      )}

      {!isLoading && !error && data && (
        <div className="flex flex-col gap-3">
          {/* Source Datasets Provenance Box */}
          <div className="rounded border border-line bg-surface-alt p-3">
            <h4 className="text-caption font-semibold uppercase tracking-header text-ink-subtle">
              Dataset Provenance & Versions
            </h4>
            <div className="mt-1 space-y-1.5">
              {sources.map((src) => (
                <div key={src.dataset_version_id} className="text-caption text-ink">
                  <div className="flex items-center gap-2">
                    <span className="font-medium">{src.dataset_name}</span>
                    <span className="rounded bg-surface px-1.5 py-0.5 font-mono text-badge text-ink-muted border border-line">
                      {src.dataset_version_id}
                    </span>
                  </div>
                  <div className="truncate text-ink-subtle" title={src.source_file}>
                    {src.source_file}
                  </div>
                </div>
              ))}
            </div>
          </div>

          {/* Search box */}
          <div className="flex items-center gap-2">
            <input
              type="text"
              placeholder="Search records (district, year, etc.)..."
              value={filterText}
              onChange={(e) => setFilterText(e.target.value)}
              className="w-full rounded border border-line bg-surface px-3 py-1.5 text-body text-ink placeholder:text-ink-subtle focus:border-primary focus:outline-none focus:ring-1 focus:ring-primary"
            />
            {filterText && (
              <button
                type="button"
                onClick={() => setFilterText('')}
                className="rounded border border-line px-2 py-1.5 text-caption text-ink-muted hover:bg-surface-alt"
              >
                Clear
              </button>
            )}
          </div>

          {records.length === 0 ? (
            <EmptyState
              title="No matching records"
              detail={filterText ? 'No rows match your search filter.' : 'No records found for this drill-down.'}
            />
          ) : (
            <div className="overflow-x-auto rounded border border-line">
              <table className="w-full text-left text-body">
                <thead className="border-b border-line bg-surface-alt text-caption font-semibold uppercase tracking-header text-ink-subtle">
                  <tr>
                    <th className="px-3 py-2">Period</th>
                    <th className="px-3 py-2">District / Grain</th>
                    <th className="px-3 py-2">Crop / Product</th>
                    <th className="px-3 py-2 text-right">Value</th>
                    <th className="px-3 py-2">Provenance</th>
                    <th className="px-3 py-2">Status</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-line bg-surface font-normal">
                  {records.map((r, i) => {
                    const period = String(r.month || r.season || r.agri_year || '—');
                    const loc = String(r.district_name || r.block_name || 'State');
                    const item = String(r.crop_name || r.land_use_category || '—');
                    const val = r.value !== null && r.value !== undefined ? Number(r.value) : null;
                    const unit = String(r.unit || '');
                    const origin = String(r.data_origin || '');
                    const grain = r.grain_source as string | undefined;
                    const status = String(r.value_status || 'ok');

                    return (
                      <tr key={i} className="hover:bg-surface-alt/60">
                        <td className="whitespace-nowrap px-3 py-2 text-caption text-ink">
                          <Figure>{period}</Figure>
                          {Boolean(r.agri_year) && r.agri_year !== period && (
                            <span className="block text-badge text-ink-subtle">{String(r.agri_year)}</span>
                          )}
                        </td>
                        <td className="px-3 py-2">
                          <span className="font-medium text-ink">{loc}</span>
                          {grain && grain !== 'published_district' && (
                            <span className="mt-0.5 block text-badge text-ink-subtle">
                              {grain === 'aggregated_from_blocks' ? 'aggregated from blocks' : 'block grain'}
                            </span>
                          )}
                        </td>
                        <td className="px-3 py-2 text-ink">
                          <span>{item}</span>
                          {Boolean(r.product) && r.product !== 'minor' && (
                            <span className="ml-1 rounded bg-surface-alt px-1 py-0.2 text-badge text-ink-muted border border-line">
                              {String(r.product)}
                            </span>
                          )}
                        </td>
                        <td className="whitespace-nowrap px-3 py-2 text-right font-medium text-ink">
                          {val !== null ? (
                            <>
                              <Figure>{val.toLocaleString('en-IN')}</Figure>{' '}
                              <span className="text-caption text-ink-muted">{unit}</span>
                            </>
                          ) : (
                            <span className="text-caption text-ink-subtle" title="No value recorded">—</span>
                          )}
                        </td>
                        <td className="whitespace-nowrap px-3 py-2">
                          <span className="text-caption text-ink-muted">
                            {origin === 'synthetic' ? 'Modelled' : 'Official'}
                          </span>
                        </td>
                        <td className="whitespace-nowrap px-3 py-2 text-caption">
                          <span
                            className={
                              status === 'ok'
                                ? 'text-success'
                                : status === 'structurally_absent'
                                ? 'text-ink-subtle'
                                : 'text-warning'
                            }
                          >
                            {status.replaceAll('_', ' ')}
                          </span>
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
          )}
        </div>
      )}
    </Drawer>
  );
}
