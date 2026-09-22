/**
 * Loading, empty and error states — DESIGN.md §7.
 *
 * Empty says what is missing and why. Error says what failed, what still works
 * and offers a retry. Loading is a skeleton matching the final layout, never a
 * full-page spinner and never a jump.
 */
import type { ReactNode } from 'react';

import { ApiError, BackendUnreachableError } from '@/api/client';
import { cn } from '@/components/primitives';

export function LoadingState({
  label,
  rows = 4,
  className,
}: {
  label: string;
  rows?: number;
  className?: string;
}) {
  return (
    <div className={cn('animate-pulse', className)} role="status" aria-live="polite">
      <span className="sr-only">{label}</span>
      <div className="space-y-2" aria-hidden="true">
        {Array.from({ length: rows }, (_, index) => (
          <div
            key={index}
            className="h-row rounded border border-line bg-surface-alt"
            // Calculated per row, so it cannot be a utility class: the
            // skeleton fades down the stack rather than pulsing flat.
            style={{ opacity: 1 - index * 0.12 }}
          />
        ))}
      </div>
    </div>
  );
}

export function EmptyState({
  title,
  detail,
  action,
}: {
  title: string;
  /** Why it is empty, in plain words. Never leave the reader guessing. */
  detail: string;
  action?: ReactNode;
}) {
  return (
    <div className="rounded border border-dashed border-line-strong bg-surface-alt px-card py-8 text-center">
      <p className="text-section font-medium text-ink">{title}</p>
      <p className="mx-auto mt-1 max-w-xl text-body text-ink-muted">{detail}</p>
      {action && <div className="mt-3 flex justify-center">{action}</div>}
    </div>
  );
}

function describe(error: unknown): { title: string; detail: string; stillWorks?: string } {
  if (error instanceof BackendUnreachableError) {
    return {
      title: 'The backend is not responding',
      detail:
        'The API on port 8001 could not be reached. Start it with ' +
        '`python -m uvicorn app.api.main:app --port 8001` and retry.',
      stillWorks: 'Navigation and previously loaded screens still work.',
    };
  }
  if (error instanceof ApiError) {
    if (error.status === 404) {
      return { title: 'Not found', detail: error.message };
    }
    return {
      title: `Request rejected (${error.status})`,
      detail: error.allowedValues?.length
        ? `${error.message} Allowed: ${error.allowedValues.slice(0, 8).join(', ')}.`
        : error.message,
    };
  }
  return {
    title: 'Something went wrong',
    detail: error instanceof Error ? error.message : 'An unexpected error occurred.',
  };
}

export function ErrorState({
  error,
  onRetry,
  compact = false,
}: {
  error: unknown;
  onRetry?: () => void;
  compact?: boolean;
}) {
  const { title, detail, stillWorks } = describe(error);
  return (
    <div
      role="alert"
      className={cn(
        'rounded border border-error/30 bg-error-bg',
        compact ? 'px-3 py-2' : 'px-card py-4',
      )}
    >
      <p className="text-body font-medium text-error">{title}</p>
      <p className="mt-1 text-body text-ink-muted">{detail}</p>
      {stillWorks && <p className="mt-1 text-caption text-ink-subtle">{stillWorks}</p>}
      {onRetry && (
        <button
          type="button"
          onClick={onRetry}
          className="mt-3 rounded border border-error/40 bg-surface px-3 py-1.5 text-body font-medium text-error transition-colors duration-state hover:bg-error-bg"
        >
          Retry
        </button>
      )}
    </div>
  );
}

/** Wraps an async panel so every screen handles the three states the same way. */
export function AsyncPanel<T>({
  query,
  loadingLabel,
  loadingRows,
  empty,
  children,
}: {
  query: {
    data: T | undefined;
    isPending: boolean;
    isError: boolean;
    error: unknown;
    refetch: () => void;
  };
  loadingLabel: string;
  loadingRows?: number;
  empty?: { title: string; detail: string };
  children: (data: T) => ReactNode;
}) {
  if (query.isPending) return <LoadingState label={loadingLabel} rows={loadingRows} />;
  if (query.isError)
    return <ErrorState error={query.error} onRetry={() => query.refetch()} />;
  if (query.data === undefined) return null;
  if (empty && Array.isArray(query.data) && query.data.length === 0) {
    return <EmptyState title={empty.title} detail={empty.detail} />;
  }
  return <>{children(query.data)}</>;
}
