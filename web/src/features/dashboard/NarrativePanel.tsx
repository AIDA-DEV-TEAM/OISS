/**
 * "What this view shows" — RFP area 4.
 *
 * The backend computes the view's facts in SQL and the model describes them;
 * every number in the paragraph is checked against those facts before it is
 * returned. The facts sit beside the prose so a reader can check each one, and
 * the panel says what wrote the paragraph: the model, or — when no model is
 * available — a plain template over the same facts.
 */
import type { QuerySpec } from '@/api/client';
import { useDashboardNarrative } from '@/api/narrative';
import { Badge, Card, Figure } from '@/components/primitives';
import { CaveatList } from '@/components/provenance';
import { ProvenanceNote } from '@/components/ProvenanceNote';
import { ErrorState, LoadingState } from '@/components/states';
import { contextFromApplied } from '@/lib/exportContext';
import type { PanelExport } from '@/lib/exportContext';

interface NarrativePanelProps {
  /** The view's own query: the narrative describes exactly what it selects. */
  spec: QuerySpec;
  /** Title used for the exported file. */
  title: string;
  onExport?: (panel: PanelExport) => void;
}

function authorship(source: string, model: string | null | undefined): string {
  if (source === 'template') {
    return 'Stated from the figures by a template: no language model was available for this view.';
  }
  const writer = model === 'fixture' ? 'a recorded response (fixture)' : (model ?? 'the model');
  return `Written by ${writer}. Every figure in it was checked against the facts listed here.`;
}

export function NarrativePanel({ spec, title, onExport }: NarrativePanelProps) {
  const narrative = useDashboardNarrative(spec);
  const data = narrative.data;

  return (
    <Card
      title="What this view shows"
      description="A description of the figures on this page, computed in SQL. The language model only puts them into words."
      note={
        data?.served_from_cache ? (
          <Badge tone="info" className="mt-1">
            Served from cache
          </Badge>
        ) : null
      }
      actions={
        onExport &&
        data && (
          <button
            type="button"
            onClick={() =>
              onExport({
                // The facts, not the prose, are the checkable content; they
                // travel as the file's rows with the view's own context.
                title,
                spec: null,
                rows: data.facts_used,
                context: contextFromApplied(title, data.applied_context, data.caveats),
              })
            }
            className="rounded border border-line bg-surface px-2.5 py-1 text-caption font-medium text-ink-muted transition-colors duration-state hover:bg-surface-alt hover:text-ink focus:outline-none focus:ring-1 focus:ring-primary"
          >
            Export
          </button>
        )
      }
    >
      {narrative.isPending && <LoadingState label="Describing this view" rows={4} />}
      {narrative.isError && (
        <ErrorState error={narrative.error} onRetry={() => narrative.refetch()} />
      )}
      {data && (
        <div className="grid grid-cols-1 gap-card lg:grid-cols-3">
          <div className="lg:col-span-2">
            <ProvenanceNote className="mb-2" context={data.applied_context} />
            <p className="text-section leading-relaxed text-ink">{data.narrative}</p>
            <p className="mt-2 text-caption text-ink-muted">
              {authorship(data.narrative_source, data.model)}
            </p>
            {data.caveats.length > 0 && <CaveatList className="mt-3" caveats={data.caveats} />}
          </div>

          <div className="rounded border border-line bg-surface-alt px-card py-3">
            <h3 className="text-caption font-medium uppercase tracking-header text-ink-subtle">
              Facts used
            </h3>
            <dl className="mt-2 space-y-2">
              {data.facts_used.map((fact) => (
                <div key={`${fact.label}-${fact.scope ?? ''}`}>
                  <dt className="text-caption text-ink-muted">
                    {fact.label}
                    {fact.scope && <span className="text-ink-subtle"> · {fact.scope}</span>}
                  </dt>
                  <dd className="text-body font-medium text-ink">
                    {fact.value === null || fact.value === undefined ? (
                      <span className="text-ink-subtle" title="No value recorded">
                        —
                      </span>
                    ) : (
                      <>
                        <Figure>
                          {fact.value.toLocaleString('en-IN', { maximumFractionDigits: 2 })}
                        </Figure>{' '}
                        <span className="text-caption font-normal text-ink-muted">{fact.unit}</span>
                      </>
                    )}
                  </dd>
                </div>
              ))}
            </dl>
          </div>
        </div>
      )}
    </Card>
  );
}
