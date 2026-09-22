/**
 * Grounded dashboard narrative — RFP area 4.
 *
 * The model verbalises a fact bundle; it never computes. Showing the facts
 * beside the prose is the point: a reader can check every number in the
 * paragraph against the list that produced it, which is what makes the
 * narrative defensible in front of a statistics directorate.
 */
import { useDashboardNarrative } from '@/api/narrative';
import type { NarrativeView } from '@/api/narrative';
import { Card, Figure } from '@/components/primitives';
import { CaveatList } from '@/components/provenance';
import { ProvenanceNote } from '@/components/ProvenanceNote';
import { ErrorState, LoadingState } from '@/components/states';

export function NarrativePanel({
  view,
  onExport,
}: {
  view: NarrativeView;
  onExport?: () => void;
}) {
  const narrative = useDashboardNarrative(view);

  return (
    <Card
      title="What this view shows"
      description="Generated from the figures on this page. Every number below is quoted from the fact bundle, not computed by the model."
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
      {narrative.isPending && <LoadingState label="Composing narrative" rows={4} />}
      {narrative.isError && (
        <ErrorState error={narrative.error} onRetry={() => narrative.refetch()} />
      )}
      {narrative.data && (
        <div className="grid grid-cols-1 gap-card lg:grid-cols-3">
          <div className="lg:col-span-2">
            <ProvenanceNote
              className="mb-2"
              signals={{
                dataOrigin: narrative.data.data_origin,
                grainSource: narrative.data.grain_source,
              }}
            />
            <p className="text-section leading-relaxed text-ink">{narrative.data.narrative}</p>
            {narrative.data.caveats.length > 0 && (
              <CaveatList className="mt-3" caveats={narrative.data.caveats} />
            )}
          </div>

          <div className="rounded border border-line bg-surface-alt px-card py-3">
            <h3 className="text-caption font-medium uppercase tracking-header text-ink-subtle">
              Facts used
            </h3>
            <dl className="mt-2 space-y-2">
              {narrative.data.facts_used.map((fact) => (
                <div key={`${fact.label}-${fact.scope ?? ''}`}>
                  <dt className="text-caption text-ink-muted">
                    {fact.label}
                    {fact.scope && <span className="text-ink-subtle"> · {fact.scope}</span>}
                  </dt>
                  <dd className="text-body font-medium text-ink">
                    {fact.value === null ? (
                      <span className="text-ink-subtle" title="No value recorded">
                        —
                      </span>
                    ) : (
                      <>
                        <Figure>{fact.value.toLocaleString('en-IN')}</Figure>{' '}
                        <span className="text-caption font-normal text-ink-muted">
                          {fact.unit}
                        </span>
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
