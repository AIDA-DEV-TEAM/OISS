/**
 * The free-text question box, with the starter questions as chips that fill it.
 *
 * The input never locks: while an answer is on its way the box stays
 * editable and a live status line says what is happening and for how long.
 */
import { useState } from 'react';

import type { StarterQuestion } from '@/api/client';
import { cn } from '@/components/primitives';
import { useElapsedSeconds } from '@/hooks/useElapsedSeconds';

interface QuestionComposerProps {
  starters: StarterQuestion[] | undefined;
  pending: boolean;
  onAsk: (question: string) => void;
}

const MAX_LENGTH = 500;

export function QuestionComposer({ starters, pending, onAsk }: QuestionComposerProps) {
  const [question, setQuestion] = useState('');
  const elapsed = useElapsedSeconds(pending);
  const trimmed = question.trim();

  const handleSubmit = (event: React.FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    if (trimmed && !pending) onAsk(trimmed);
  };

  const handleKeyDown = (event: React.KeyboardEvent<HTMLTextAreaElement>) => {
    // Enter asks; Shift+Enter keeps a line break for a long question.
    if (event.key === 'Enter' && !event.shiftKey) {
      event.preventDefault();
      if (trimmed && !pending) onAsk(trimmed);
    }
  };

  return (
    <form onSubmit={handleSubmit} aria-busy={pending}>
      <label htmlFor="assistant-question" className="text-body font-medium text-ink">
        Your question
      </label>
      <p id="assistant-question-help" className="mt-0.5 text-caption text-ink-muted">
        Ask about crop area, production, yield, prices or land use in Odisha. Enter asks;
        Shift+Enter adds a line.
      </p>
      <textarea
        id="assistant-question"
        aria-describedby="assistant-question-help"
        value={question}
        maxLength={MAX_LENGTH}
        rows={2}
        onChange={(event) => setQuestion(event.target.value)}
        onKeyDown={handleKeyDown}
        placeholder="For example: which districts produced the most paddy in 2024-25?"
        className="mt-2 w-full resize-y rounded border border-line bg-surface px-3 py-2 text-body text-ink placeholder:text-ink-subtle focus:border-primary focus:outline-none focus:ring-1 focus:ring-primary"
      />
      <div className="mt-2 flex flex-wrap items-center gap-3">
        <button
          type="submit"
          disabled={!trimmed || pending}
          className="min-h-11 rounded border border-primary bg-primary px-4 py-1.5 text-body font-medium text-surface transition-colors duration-state hover:bg-primary-hover focus:outline-none focus:ring-2 focus:ring-primary focus:ring-offset-1 disabled:opacity-60"
        >
          {pending ? 'Answering…' : 'Ask'}
        </button>
        <p role="status" aria-live="polite" className="text-caption text-ink-muted">
          {pending
            ? `Reading the question, running the query and checking every figure in the answer… ${elapsed}s`
            : ''}
        </p>
      </div>

      {starters && starters.length > 0 && (
        <div className="mt-4">
          <p className="text-caption font-medium uppercase tracking-header text-ink-subtle">
            Starter questions
          </p>
          <ul className="mt-1.5 flex flex-wrap gap-2">
            {starters.map((starter) => (
              <li key={starter.question_id}>
                <button
                  type="button"
                  onClick={() => setQuestion(starter.question)}
                  aria-pressed={question === starter.question}
                  className={cn(
                    'min-h-11 rounded border px-3 py-1.5 text-left text-body transition-colors duration-state focus:outline-none focus:ring-1 focus:ring-primary',
                    question === starter.question
                      ? 'border-primary bg-primary-subtle font-medium text-primary'
                      : 'border-line bg-surface text-ink-muted hover:bg-surface-alt hover:text-ink',
                  )}
                >
                  {starter.question}
                </button>
              </li>
            ))}
          </ul>
        </div>
      )}
    </form>
  );
}
