/**
 * Conversational analytics assistant — RFP area 5.
 *
 * The model never computes and never writes SQL: it turns a question into a
 * query spec, the backend validates and executes it, and the model verbalises
 * the rows under a no-new-numbers check. Every answer therefore arrives with
 * the things a statistician asks for next — the filters applied, the source
 * dataset, the reporting period, the supporting records, the caveats — and
 * with the query the question was read as.
 *
 * Declining is part of the design. A question that needs data the system does
 * not hold is refused with the reason, which reads as more trustworthy than a
 * system that always produces a number.
 */
import { useState } from 'react';

import { useAskAssistant, useStarterQuestions } from '@/api/assistant';
import { ExportModal } from '@/components/ExportModal';
import { PageHeader } from '@/components/PageHeader';
import { Card } from '@/components/primitives';
import { EmptyState, ErrorState, LoadingState } from '@/components/states';
import { AnswerCard } from '@/features/assistant/AnswerCard';
import { DeclinedCard } from '@/features/assistant/DeclinedCard';
import { QuestionComposer } from '@/features/assistant/QuestionComposer';
import { contextFromApplied } from '@/lib/exportContext';

export function AssistantPage() {
  const starters = useStarterQuestions();
  const ask = useAskAssistant();
  const [exportOpen, setExportOpen] = useState(false);

  const answer = ask.data;
  const asked = ask.variables;

  return (
    <>
      <PageHeader
        title="Analytics assistant"
        description="Ask a question in plain language. The assistant reads it as a query, validates and runs that query against the loaded data, and checks every figure in its answer against the result."
      />

      <div className="space-y-4">
        <Card
          title="Ask"
          description="Answers come only from the loaded datasets. A question that needs anything else — policy, general knowledge, years or grains the data does not cover — is declined with the reason. Declining accurately is intended behaviour."
        >
          {starters.isError && (
            <ErrorState
              error={starters.error}
              onRetry={() => starters.refetch()}
            />
          )}
          <QuestionComposer
            starters={starters.data}
            pending={ask.isPending}
            onAsk={(question) => ask.mutate(question)}
          />
        </Card>

        {ask.isIdle && (
          <EmptyState
            title="No question asked yet"
            detail="Type a question or pick a starter. Each answer carries the filters it applied, the datasets it read, the period it covers, any caveats, and how the question was read."
          />
        )}

        {ask.isPending && <LoadingState label={`Answering: ${asked ?? ''}`} rows={6} />}
        {ask.isError && asked && (
          <ErrorState error={ask.error} onRetry={() => ask.mutate(asked)} />
        )}
        {ask.isSuccess && answer && (
          answer.status === 'answered' ? (
            <AnswerCard answer={answer} onExport={() => setExportOpen(true)} />
          ) : (
            <DeclinedCard answer={answer} />
          )
        )}
      </div>

      <ExportModal
        open={exportOpen}
        onClose={() => setExportOpen(false)}
        exportType="assistant_answer"
        panel={
          answer && answer.status === 'answered'
            ? {
                // The validated spec behind the answer: the export service
                // re-runs it, so the file's context is derived, not supplied.
                title: answer.question,
                spec: answer.query_spec ?? null,
                rows: answer.rows,
                context: contextFromApplied(
                  answer.question,
                  answer.applied_context,
                  answer.caveats,
                ),
              }
            : null
        }
      />
    </>
  );
}
