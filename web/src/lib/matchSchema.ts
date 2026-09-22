/**
 * Matches an uploaded file's own header to the dataset whose schema it fits.
 *
 * The ingest screen used to default the target to whichever dataset happened to
 * sort first, so a price CSV arrived labelled as block land use and was handed
 * to the wrong reader. The file's columns are the only honest basis for the
 * choice, so they make it.
 */
import type { IngestSchema } from '@/api/client';

export interface SchemaMatch {
  schema: IngestSchema;
  /** Declared columns present in the file, over the size of the union. */
  score: number;
  missing: string[];
  unexpected: string[];
}

function normalise(column: string): string {
  return column.trim().toLowerCase();
}

/** Jaccard overlap between the file's header and a declared schema. */
export function scoreSchema(columns: string[], schema: IngestSchema): SchemaMatch {
  const present = new Set(columns.map(normalise));
  const expected = new Set(schema.expected_columns.map(normalise));

  const missing = schema.expected_columns.filter((c) => !present.has(normalise(c)));
  const unexpected = columns.filter((c) => !expected.has(normalise(c)));

  const union = new Set([...present, ...expected]);
  const overlap = expected.size - missing.length;
  return {
    schema,
    score: union.size === 0 ? 0 : overlap / union.size,
    missing,
    unexpected,
  };
}

/**
 * The best-fitting schema, or null when nothing fits well enough to choose for
 * the user. Below the threshold the screen leaves the target unset and says so,
 * rather than picking one and letting the mismatch surface as a surprise.
 */
export function matchSchema(
  columns: string[],
  schemas: IngestSchema[],
  threshold = 0.6,
): SchemaMatch | null {
  if (columns.length === 0 || schemas.length === 0) return null;
  const ranked = schemas
    .map((schema) => scoreSchema(columns, schema))
    // Ties resolve by name so the same file always picks the same dataset.
    .sort((a, b) => b.score - a.score || a.schema.dataset_name.localeCompare(b.schema.dataset_name));
  const best = ranked[0];
  return best.score >= threshold ? best : null;
}
