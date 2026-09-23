/**
 * "How this was answered": the query the question was read as.
 *
 * A reader must be able to see how their words were interpreted — which
 * metric, grouped how, filtered to what, over which years — and what did the
 * reading, so a wrong interpretation is visible rather than hidden behind a
 * confident paragraph.
 */
import type { AssistantAnswer, Interpretation } from '@/api/client';
import { filterPhrase } from '@/lib/exportContext';

interface InterpretedQueryProps {
  interpretation: Interpretation;
  answer: AssistantAnswer;
}

function readerLabel(model: string): string {
  return model === 'fixture'
    ? 'Recorded response (fixture), checked like a live one'
    : model;
}

export function InterpretedQuery({ interpretation, answer }: InterpretedQueryProps) {
  const rows: Array<[string, string]> = [
    ['Metric', `${interpretation.metric_label} (${interpretation.unit})`],
    [
      'Grouped by',
      interpretation.dimensions.length
        ? interpretation.dimensions.map((d) => d.label).join(', ')
        : 'Nothing: one figure',
    ],
    [
      'Filters',
      interpretation.filters.length
        ? interpretation.filters.map(filterPhrase).join(' · ')
        : 'None',
    ],
    ['Period', interpretation.period ?? 'Not pinned'],
    ['Order', interpretation.order ?? 'As stored'],
    ['Question read by', readerLabel(interpretation.model)],
    [
      'Answer written by',
      answer.answer_source === 'template'
        ? 'Template: the model’s wording quoted a figure not in the result, so the rows are stated directly'
        : answer.answer_source === 'model'
          ? 'The model, with every figure checked against the result'
          : '—',
    ],
  ];

  return (
    <details className="mt-4 rounded border border-line bg-surface-alt">
      <summary className="cursor-pointer px-3 py-2 text-body font-medium text-ink focus:outline-none focus:ring-1 focus:ring-primary">
        How this was answered
      </summary>
      <div className="border-t border-line px-3 py-3">
        <dl className="grid grid-cols-1 gap-x-gutter gap-y-2 sm:grid-cols-[10rem_1fr]">
          {rows.map(([term, value]) => (
            <div key={term} className="contents">
              <dt className="text-caption font-medium uppercase tracking-header text-ink-subtle">
                {term}
              </dt>
              <dd className="text-body text-ink">{value}</dd>
            </div>
          ))}
        </dl>
        {interpretation.corrected && (
          <p className="mt-2 text-caption text-ink-muted">
            The first reading was rejected by the query validator; this is the corrected one.
          </p>
        )}
        <p className="mt-3 text-caption text-ink-muted">
          The model chose only this query. The backend validated it against the registry and
          ran it; the model never sees SQL or the database.
        </p>
        {answer.query_spec && (
          <pre className="mt-2 overflow-x-auto rounded border border-line bg-surface p-2 text-caption text-ink">
            {JSON.stringify(answer.query_spec, null, 2)}
          </pre>
        )}
      </div>
    </details>
  );
}
