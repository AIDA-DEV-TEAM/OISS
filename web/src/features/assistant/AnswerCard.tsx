/**
 * One answered question: the paragraph, the chart, and everything a
 * statistician asks next — filters, source, period, records, caveats — plus
 * how the question was read.
 */
import type { AssistantAnswer } from '@/api/client';
import { Badge, Card, Figure } from '@/components/primitives';
import { CaveatList } from '@/components/provenance';
import { ProvenanceNote } from '@/components/ProvenanceNote';
import { AnswerChart } from '@/features/assistant/AnswerChart';
import { InterpretedQuery } from '@/features/assistant/InterpretedQuery';
import { RecordsTable } from '@/features/assistant/RecordsTable';
import { filterPhrase } from '@/lib/exportContext';

interface AnswerCardProps {
  answer: AssistantAnswer;
  onExport: () => void;
}

export function AnswerCard({ answer, onExport }: AnswerCardProps) {
  const meta: Array<[string, React.ReactNode]> = [
    [
      'Applied filters',
      answer.applied_filters.length
        ? answer.applied_filters.map(filterPhrase).join(' · ')
        : 'None',
    ],
    [
      'Source dataset',
      answer.source_datasets.length
        ? answer.source_datasets.map((d) => d.dataset_name).join(', ')
        : 'None',
    ],
    ['Reporting period', answer.period ?? 'All years in the selection'],
    [
      'Supporting records',
      <>
        <Figure>{answer.records_preview.length.toLocaleString('en-IN')}</Figure> of{' '}
        <Figure>{answer.records_total.toLocaleString('en-IN')}</Figure> shown
      </>,
    ],
  ];

  return (
    <Card
      title={answer.question}
      note={
        answer.served_from_cache ? (
          <Badge
            tone="info"
            className="mt-1"
            title="This question was answered before; the stored response was replayed rather than asking the model again."
          >
            Served from cache
          </Badge>
        ) : null
      }
      actions={
        <button
          type="button"
          onClick={onExport}
          className="min-h-11 rounded border border-line bg-surface px-2.5 py-1 text-caption font-medium text-ink-muted transition-colors duration-state hover:bg-surface-alt hover:text-ink focus:outline-none focus:ring-1 focus:ring-primary"
        >
          Export
        </button>
      }
    >
      <ProvenanceNote className="mb-2" context={answer.applied_context} />
      <p className="text-section leading-relaxed text-ink">{answer.answer}</p>

      {answer.chart_spec && <AnswerChart spec={answer.chart_spec} />}

      <dl className="mt-4 grid grid-cols-1 gap-x-gutter gap-y-3 border-t border-line pt-3 sm:grid-cols-2 xl:grid-cols-4">
        {meta.map(([term, value]) => (
          <div key={term} className="min-w-0">
            <dt className="text-caption font-medium uppercase tracking-header text-ink-subtle">
              {term}
            </dt>
            <dd className="mt-0.5 break-words text-body text-ink">{value}</dd>
          </div>
        ))}
      </dl>

      <RecordsTable records={answer.records_preview} />

      {answer.caveats.length > 0 && <CaveatList className="mt-3" caveats={answer.caveats} />}

      {answer.interpretation && (
        <InterpretedQuery interpretation={answer.interpretation} answer={answer} />
      )}
    </Card>
  );
}
