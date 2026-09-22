/**
 * Small shared primitives: Card, StatCard, Badge, SeverityChip, Figure.
 *
 * Everything is styled from the Tailwind theme, which mirrors DESIGN.md §2.
 * No component carries a hex literal or an arbitrary value.
 */
import type { ReactNode } from 'react';

export function cn(...parts: Array<string | false | null | undefined>): string {
  return parts.filter(Boolean).join(' ');
}

/** DESIGN.md §3: every figure uses tabular numerals so columns align. */
export function Figure({
  children,
  className,
}: {
  children: ReactNode;
  className?: string;
}) {
  return <span className={cn('figure', className)}>{children}</span>;
}

interface CardProps {
  title?: ReactNode;
  description?: ReactNode;
  /** The panel's ProvenanceNote, rendered directly under the title (DESIGN.md §5). */
  note?: ReactNode;
  actions?: ReactNode;
  children: ReactNode;
  /** Chart cards get 20px padding; everything else 16px (DESIGN.md §4). */
  chart?: boolean;
  className?: string;
  bodyClassName?: string;
}

export function Card({
  title,
  description,
  note,
  actions,
  children,
  chart = false,
  className,
  bodyClassName,
}: CardProps) {
  return (
    <section
      className={cn(
        'rounded-card border border-line bg-surface shadow-card',
        className,
      )}
    >
      {(title || actions || note) && (
        <header
          className={cn(
            'flex items-start justify-between gap-4 border-b border-line',
            chart ? 'px-card-chart py-3' : 'px-card py-3',
          )}
        >
          <div className="min-w-0">
            {title && <h2 className="text-title font-semibold text-ink">{title}</h2>}
            {description && (
              <p className="mt-0.5 text-caption text-ink-muted">{description}</p>
            )}
            {note}
          </div>
          {actions && <div className="flex shrink-0 items-center gap-2">{actions}</div>}
        </header>
      )}
      <div className={cn(chart ? 'p-card-chart' : 'p-card', bodyClassName)}>
        {children}
      </div>
    </section>
  );
}

export function StatCard({
  label,
  value,
  unit,
  hint,
  badge,
}: {
  label: string;
  value: ReactNode;
  unit?: string;
  hint?: ReactNode;
  badge?: ReactNode;
}) {
  return (
    <div className="rounded-card border border-line bg-surface p-card shadow-card">
      <div className="flex items-start justify-between gap-2">
        <p className="text-caption font-medium text-ink-muted">{label}</p>
        {badge}
      </div>
      <p className="mt-1 flex items-baseline gap-1.5">
        <Figure className="text-kpi font-semibold text-ink">{value}</Figure>
        {unit && <span className="text-caption text-ink-muted">{unit}</span>}
      </p>
      {hint && <p className="mt-1 text-caption text-ink-subtle">{hint}</p>}
    </div>
  );
}

type Tone = 'neutral' | 'info' | 'error' | 'warning' | 'success' | 'primary';

const TONE_CLASS: Record<Tone, string> = {
  neutral: 'bg-surface-alt text-ink-muted border-line',
  info: 'bg-info-bg text-info border-info/30',
  error: 'bg-error-bg text-error border-error/30',
  warning: 'bg-warning-bg text-warning border-warning/30',
  success: 'bg-success-bg text-success border-success/30',
  primary: 'bg-primary-subtle text-primary border-primary/30',
};

/** DESIGN.md §5: 11px, 500 weight, 2px radius, 1px border, no uppercase. */
export function Badge({
  children,
  tone = 'neutral',
  title,
  className,
}: {
  children: ReactNode;
  tone?: Tone;
  title?: string;
  className?: string;
}) {
  return (
    <span
      title={title}
      className={cn(
        'inline-flex items-center gap-1 whitespace-nowrap rounded-badge border px-1.5 py-0.5 text-badge font-medium',
        TONE_CLASS[tone],
        className,
      )}
    >
      {children}
    </span>
  );
}

export type Severity = 'error' | 'warning' | 'info';

const SEVERITY_LABEL: Record<Severity, string> = {
  error: 'Error',
  warning: 'Warning',
  info: 'Info',
};

/** DESIGN.md §5: validation findings, status tokens. Severity is never colour
 *  alone — the word is always present. */
export function SeverityChip({
  severity,
  count,
}: {
  severity: Severity;
  count?: number;
}) {
  const tone: Tone = severity === 'error' ? 'error' : severity === 'warning' ? 'warning' : 'info';
  return (
    <Badge tone={tone}>
      {SEVERITY_LABEL[severity]}
      {count !== undefined && (
        <>
          <span aria-hidden="true">·</span>
          <Figure>{count.toLocaleString('en-IN')}</Figure>
        </>
      )}
    </Badge>
  );
}

export function SectionHeading({
  children,
  hint,
}: {
  children: ReactNode;
  hint?: ReactNode;
}) {
  return (
    <div className="mb-2 flex items-baseline justify-between gap-3">
      <h3 className="text-section font-semibold text-ink">{children}</h3>
      {hint && <span className="text-caption text-ink-muted">{hint}</span>}
    </div>
  );
}

/** Key/value pairs used by dataset metadata panels. */
export function DefinitionList({
  items,
}: {
  items: Array<{ term: string; value: ReactNode; wide?: boolean }>;
}) {
  return (
    <dl className="grid grid-cols-1 gap-x-gutter gap-y-3 sm:grid-cols-2 xl:grid-cols-3">
      {items.map((item) => (
        <div key={item.term} className={item.wide ? 'sm:col-span-2 xl:col-span-3' : undefined}>
          <dt className="text-caption font-medium text-ink-muted">{item.term}</dt>
          <dd className="mt-0.5 break-words text-body text-ink">{item.value}</dd>
        </div>
      ))}
    </dl>
  );
}
