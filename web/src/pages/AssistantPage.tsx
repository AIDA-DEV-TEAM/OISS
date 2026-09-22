/**
 * Conversational analytics assistant — RFP area 5.
 *
 * The model never computes and never writes SQL: it turns a question into a
 * validated query spec, the backend executes it, and the model verbalises the
 * rows. Every answer therefore arrives with the things a statistician asks for
 * next — the filters applied, the source dataset, the reporting period, the
 * supporting records and the caveats.
 *
 * One of the predefined questions is declined on purpose. A system that says
 * "this data does not exist" reads as more trustworthy than one that always
 * produces a number.
 */
import { useState } from 'react';
import {
  Bar,
  BarChart,
  CartesianGrid,
  Line,
  LineChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from 'recharts';

import type { AssistantAnswer } from '@/api/contracts';
import { useAskAssistant, useAssistantQuestions } from '@/api/assistant';
import { ExportModal } from '@/components/ExportModal';
import { PageHeader } from '@/components/PageHeader';
import { Card, Figure, cn } from '@/components/primitives';
import { CaveatList } from '@/components/provenance';
import { ProvenanceNote } from '@/components/ProvenanceNote';
import { EmptyState, ErrorState, LoadingState } from '@/components/states';
import { CHART_COLORS, CHART_INK } from '@/features/dashboard/constants';
import { toExportContext } from '@/lib/exportContext';

export function AssistantPage() {
  const questions = useAssistantQuestions();
  const ask = useAskAssistant();
  const [activeId, setActiveId] = useState<string | null>(null);
  const [exportOpen, setExportOpen] = useState(false);

  const answer = ask.data;

  return (
    <>
      <PageHeader
        title="Analytics assistant"
        description="Ask a question in plain language. The assistant turns it into a validated query, runs it against the loaded data, and shows the filters, sources and caveats behind the answer."
      />

      <div className="space-y-4">
        <Card
          title="Questions"
          description="Predefined questions, answered from the loaded datasets."
        >
          {questions.isPending && <LoadingState label="Loading questions" rows={2} />}
          {questions.isError && (
            <ErrorState error={questions.error} onRetry={() => questions.refetch()} />
          )}
          {questions.data && (
            <ul className="flex flex-wrap gap-2">
              {questions.data.map((q) => {
                const selected = activeId === q.question_id;
                return (
                  <li key={q.question_id}>
                    <button
                      type="button"
                      aria-pressed={selected}
                      onClick={() => {
                        setActiveId(q.question_id);
                        ask.mutate(q.question_id);
                      }}
                      className={cn(
                        'rounded border px-3 py-1.5 text-left text-body transition-colors duration-state',
                        selected
                          ? 'border-primary bg-primary-subtle font-medium text-primary'
                          : 'border-line bg-surface text-ink-muted hover:bg-surface-alt hover:text-ink',
                      )}
                    >
                      {q.question}
                    </button>
                  </li>
                );
              })}
            </ul>
          )}
        </Card>

        {!activeId && (
          <EmptyState
            title="No question asked yet"
            detail="Pick one of the questions above. Each answer carries the filters it applied, the datasets it read, the period it covers and any caveats that apply."
          />
        )}

        {activeId && ask.isPending && <LoadingState label="Answering" rows={6} />}
        {activeId && ask.isError && (
          <ErrorState error={ask.error} onRetry={() => ask.mutate(activeId)} />
        )}
        {answer && <AnswerCard answer={answer} onExport={() => setExportOpen(true)} />}
      </div>

      <ExportModal
        open={exportOpen}
        onClose={() => setExportOpen(false)}
        exportType="assistant_answer"
        context={
          answer
            ? toExportContext({
                panelTitle: answer.question,
                filters: answer.applied_filters,
                period: answer.period,
                rowCount: answer.records_preview.length,
                sources: answer.source_datasets,
                dataOrigin: answer.data_origin,
                grainSource: answer.grain_source,
                caveats: answer.caveats,
              })
            : null
        }
      />
    </>
  );
}

function AnswerCard({
  answer,
  onExport,
}: {
  answer: AssistantAnswer;
  onExport: () => void;
}) {
  if (answer.status === 'declined') {
    return (
      <Card title={answer.question}>
        <div className="border-l-rule border-l-warning bg-warning-bg px-card py-3">
          <p className="text-body font-medium text-warning">
            This cannot be answered from the loaded data
          </p>
          <p className="mt-1 text-body text-ink">{answer.answer}</p>
          {answer.limitation && (
            <p className="mt-2 text-caption text-ink-muted">{answer.limitation}</p>
          )}
        </div>
      </Card>
    );
  }

  const columns = Object.keys(answer.records_preview[0] ?? {});

  return (
    <Card
      title={answer.question}
      actions={
        <button
          type="button"
          onClick={onExport}
          className="rounded border border-line bg-surface px-2.5 py-1 text-caption font-medium text-ink-muted transition-colors duration-state hover:bg-surface-alt hover:text-ink"
        >
          Export
        </button>
      }
    >
      <ProvenanceNote
        className="mb-2"
        signals={{ dataOrigin: answer.data_origin, grainSource: answer.grain_source }}
      />
      <p className="text-section leading-relaxed text-ink">{answer.answer}</p>

      {answer.chart_spec && (
        <div className="mt-4 h-72">
          <ResponsiveContainer width="100%" height="100%">
            {answer.chart_spec.kind === 'bar' ? (
              <BarChart
                data={answer.chart_spec.data}
                margin={{ top: 8, right: 16, bottom: 56, left: 8 }}
              >
                <CartesianGrid stroke={CHART_INK.grid} vertical={false} />
                <XAxis
                  dataKey={answer.chart_spec.x_key}
                  angle={-35}
                  textAnchor="end"
                  interval={0}
                  height={56}
                  tick={{ fontSize: 12, fill: CHART_INK.axis }}
                />
                <YAxis
                  tick={{ fontSize: 12, fill: CHART_INK.axis }}
                  label={{
                    value: answer.chart_spec.unit,
                    angle: -90,
                    position: 'insideLeft',
                    style: { fontSize: 12, fill: CHART_INK.axis },
                  }}
                />
                <Tooltip contentStyle={{ fontSize: 12 }} />
                <Bar
                  dataKey={answer.chart_spec.y_key}
                  name={answer.chart_spec.series_label}
                  fill={CHART_COLORS[0]}
                />
              </BarChart>
            ) : (
              <LineChart
                data={answer.chart_spec.data}
                margin={{ top: 8, right: 16, bottom: 32, left: 8 }}
              >
                <CartesianGrid stroke={CHART_INK.grid} vertical={false} />
                <XAxis
                  dataKey={answer.chart_spec.x_key}
                  tick={{ fontSize: 12, fill: CHART_INK.axis }}
                />
                <YAxis
                  tick={{ fontSize: 12, fill: CHART_INK.axis }}
                  label={{
                    value: answer.chart_spec.unit,
                    angle: -90,
                    position: 'insideLeft',
                    style: { fontSize: 12, fill: CHART_INK.axis },
                  }}
                />
                <Tooltip contentStyle={{ fontSize: 12 }} />
                <Line
                  type="monotone"
                  dataKey={answer.chart_spec.y_key}
                  name={answer.chart_spec.series_label}
                  stroke={CHART_COLORS[0]}
                  strokeWidth={2}
                  dot={{ r: 3 }}
                  connectNulls={false}
                />
              </LineChart>
            )}
          </ResponsiveContainer>
        </div>
      )}

      <dl className="mt-4 grid grid-cols-1 gap-x-gutter gap-y-3 border-t border-line pt-3 sm:grid-cols-2 xl:grid-cols-4">
        <Meta term="Applied filters">
          {answer.applied_filters.length === 0
            ? 'None'
            : answer.applied_filters
                .map((f) => `${f.dimension}: ${f.values.join(', ')}`)
                .join(' · ')}
        </Meta>
        <Meta term="Source dataset">
          {answer.source_datasets.length === 0
            ? 'None'
            : answer.source_datasets.map((d) => d.dataset_name).join(', ')}
        </Meta>
        <Meta term="Reporting period">{answer.period ?? '—'}</Meta>
        <Meta term="Supporting records">
          <Figure>{answer.records_preview.length}</Figure> shown
        </Meta>
      </dl>

      {columns.length > 0 && (
        <div className="mt-3 overflow-x-auto rounded border border-line">
          <table className="w-full text-left text-body">
            <caption className="sr-only">Records supporting the answer</caption>
            <thead className="border-b border-line bg-surface-alt text-caption font-medium uppercase tracking-header text-ink-subtle">
              <tr>
                {columns.map((column) => (
                  <th key={column} className="px-3 py-2">
                    {column.replaceAll('_', ' ')}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody className="divide-y divide-line bg-surface">
              {answer.records_preview.map((record, index) => (
                <tr key={index} className="hover:bg-surface-alt">
                  {columns.map((column) => {
                    const value = record[column];
                    const numeric = typeof value === 'number';
                    return (
                      <td
                        key={column}
                        className={cn(
                          'whitespace-nowrap px-3 py-2 text-ink',
                          numeric && 'text-right',
                        )}
                      >
                        {value === null || value === undefined ? (
                          <span className="text-ink-subtle" title="No value recorded">
                            —
                          </span>
                        ) : numeric ? (
                          <Figure>{value.toLocaleString('en-IN')}</Figure>
                        ) : (
                          String(value)
                        )}
                      </td>
                    );
                  })}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {answer.caveats.length > 0 && <CaveatList className="mt-3" caveats={answer.caveats} />}
    </Card>
  );
}

function Meta({ term, children }: { term: string; children: React.ReactNode }) {
  return (
    <div className="min-w-0">
      <dt className="text-caption font-medium uppercase tracking-header text-ink-subtle">
        {term}
      </dt>
      <dd className="mt-0.5 break-words text-body text-ink">{children}</dd>
    </div>
  );
}
