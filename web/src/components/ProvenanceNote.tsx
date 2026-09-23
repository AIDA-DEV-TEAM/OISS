/**
 * The quiet provenance line that sits in a panel header.
 *
 * 11px, regular weight, --color-text-subtle, no chip, no border, no icon. It
 * states once, for the panel, what the per-figure badges used to repeat beside
 * every number.
 */
import type { AppliedContext } from '@/api/client';
import { cn } from '@/components/primitives';
import { notesFor, provenanceNotes } from '@/lib/provenance';
import type { ProvenanceSignals } from '@/lib/provenance';

/**
 * Renders nothing when the data is wholly official and published at its stated
 * grain — silence is the correct disclosure for an unremarkable panel.
 */
export function ProvenanceNote({
  signals,
  context,
  className,
}: {
  signals?: ProvenanceSignals;
  context?: AppliedContext | null;
  className?: string;
}) {
  const notes = signals ? provenanceNotes(signals) : notesFor(context);
  if (notes.length === 0) return null;
  return (
    <p className={cn('text-badge font-normal text-ink-subtle', className)}>
      {notes.join(' · ')}
    </p>
  );
}
