/**
 * A question the assistant did not answer, and exactly why.
 *
 * Two different reasons, shown differently: the data cannot answer it
 * (declined — a correct outcome), or no model could be reached to read a
 * question it has not seen before (unavailable — an outage).
 */
import type { AssistantAnswer } from '@/api/client';
import { Badge, Card } from '@/components/primitives';
import { InterpretedQuery } from '@/features/assistant/InterpretedQuery';

interface DeclinedCardProps {
  answer: AssistantAnswer;
}

export function DeclinedCard({ answer }: DeclinedCardProps) {
  const unavailable = answer.status === 'unavailable';

  return (
    <Card
      title={answer.question}
      note={
        answer.served_from_cache ? (
          <Badge tone="info" className="mt-1">
            Served from cache
          </Badge>
        ) : null
      }
    >
      <div
        className={
          unavailable
            ? 'border-l-rule border-l-error bg-error-bg px-card py-3'
            : 'border-l-rule border-l-warning bg-warning-bg px-card py-3'
        }
      >
        <p className={unavailable ? 'text-body font-medium text-error' : 'text-body font-medium text-warning'}>
          {unavailable
            ? 'The question could not be interpreted right now'
            : 'This cannot be answered from the loaded data'}
        </p>
        <p className="mt-1 text-body text-ink">
          {unavailable ? answer.answer : answer.limitation}
        </p>
        {unavailable && answer.limitation && (
          <p className="mt-2 text-caption text-ink-muted">Reason: {answer.limitation}</p>
        )}
      </div>
      {!unavailable && (
        <p className="mt-2 text-caption text-ink-muted">
          The assistant answers only from the loaded datasets and says so when a question needs
          anything else. Declining here is the correct answer, not a fault.
        </p>
      )}
      {answer.interpretation && (
        <InterpretedQuery interpretation={answer.interpretation} answer={answer} />
      )}
    </Card>
  );
}
