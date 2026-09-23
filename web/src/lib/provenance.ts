/**
 * Panel-level provenance disclosure.
 *
 * One quiet line in a panel header, derived from backend fields — never a
 * string typed into a component. `data_origin`, `annual_level_basis` and
 * `grain_source` are the only inputs, so a mocked panel that carries the same
 * field shape discloses identically once it is wired to a real endpoint.
 *
 * This replaces the per-figure Synthetic / Analytical Estimate chips: a column
 * of figures each wearing a badge is unreadable, and the statement belongs to
 * the panel rather than to any one number.
 *
 * The backend owns the wording (app/exports/provenance.py) and sends it as
 * `applied_context.provenance_notes`, because an exported file has to carry
 * the same line and a screen and a file must not word it differently. The
 * derivation below is the fallback for panels still fed by fixtures, which
 * have no backend context to quote.
 */
import type { AppliedContext } from '@/api/client';

/** Counts keyed by value, as `applied_context.data_origin` and `grain_source`
 *  arrive from the backend. */
export type Mix = Record<string, number>;

export interface ProvenanceSignals {
  /** official | synthetic | model — a mix, or a single row's value. */
  dataOrigin?: Mix | string | null;
  /** published | imputed | projected, for synthetic price levels. */
  annualLevelBasis?: Mix | string | null;
  /** published_district | published_block | aggregated_from_blocks. */
  grainSource?: Mix | string | null;
}

/** The exact wording. Kept here so no component can invent its own phrasing. */
const WORDING = {
  synthetic: 'Representative dataset modelled on DE&S Price Statistics, 2013-19',
  model: 'Analytical Estimates',
  aggregated: 'District figures aggregated from block-level data',
} as const;

/** True when `value` names the key, whether it arrived as a mix or a scalar. */
function present(value: Mix | string | null | undefined, key: string): boolean {
  if (!value) return false;
  if (typeof value === 'string') return value === key;
  return (value[key] ?? 0) > 0;
}

/**
 * The disclosure lines a panel owes its reader, in a fixed order so two panels
 * showing the same kind of data never word it differently.
 */
export function provenanceNotes(signals: ProvenanceSignals): string[] {
  const notes: string[] = [];
  if (present(signals.dataOrigin, 'synthetic')) notes.push(WORDING.synthetic);
  if (present(signals.dataOrigin, 'model')) notes.push(WORDING.model);
  if (present(signals.grainSource, 'aggregated_from_blocks')) notes.push(WORDING.aggregated);
  return notes;
}

/**
 * The notes for a backend result: the ones it sent, or -- for an older or
 * fixture-shaped context that carries none -- the same lines derived here.
 */
export function notesFor(context: AppliedContext | null | undefined): string[] {
  if (context?.provenance_notes && context.provenance_notes.length > 0) {
    return context.provenance_notes;
  }
  return notesFromContext(context);
}

/** Pulls the same signals out of a backend `applied_context`. */
export function signalsFromContext(context: AppliedContext | null | undefined): ProvenanceSignals {
  if (!context) return {};
  return {
    dataOrigin: context.data_origin,
    grainSource: context.grain_source ?? null,
  };
}

/** Convenience for the common case: notes straight from an applied context. */
export function notesFromContext(context: AppliedContext | null | undefined): string[] {
  return provenanceNotes(signalsFromContext(context));
}
