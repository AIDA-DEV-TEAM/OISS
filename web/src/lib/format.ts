/** Formatting helpers. Every number that reaches the screen goes through here. */

const INTEGER = new Intl.NumberFormat('en-IN', { maximumFractionDigits: 0 });

export function formatCount(value: number | null | undefined): string {
  if (value === null || value === undefined || Number.isNaN(value)) return '—';
  return INTEGER.format(value);
}

export function formatBytes(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} kB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

/** ISO timestamp to something readable on a projector, without a timezone tail. */
export function formatTimestamp(value: string | null | undefined): string {
  if (!value) return '—';
  const parsed = new Date(value);
  if (Number.isNaN(parsed.getTime())) return value;
  return parsed.toLocaleString('en-IN', {
    year: 'numeric',
    month: 'short',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
    hour12: false,
  });
}

/** Shortens a checksum for display; the full value stays in the title attribute. */
export function shortHash(sha: string | null | undefined): string {
  if (!sha) return '—';
  return `${sha.slice(0, 12)}…${sha.slice(-4)}`;
}

/** Windows paths arrive from the backend; only the filename is useful on screen. */
export function fileName(path: string | null | undefined): string {
  if (!path) return '—';
  const parts = path.split(/[\\/]/);
  return parts[parts.length - 1] || path;
}

/** RULE_CODE to 'Rule code' for headings, keeping the code itself available. */
export function humanRule(code: string): string {
  const lower = code.replaceAll('_', ' ').toLowerCase();
  return lower.charAt(0).toUpperCase() + lower.slice(1);
}

/**
 * The backend writes row_ref as `row=12|district=Angul|crop=Paddy`. Splitting it
 * gives the row index plus the series the finding belongs to, which is what the
 * detail view shows.
 */
export function parseRowRef(rowRef: string | null | undefined): {
  row: string | null;
  series: Array<{ key: string; value: string }>;
} {
  if (!rowRef) return { row: null, series: [] };
  const parts = rowRef.split('|');
  let row: string | null = null;
  const series: Array<{ key: string; value: string }> = [];
  for (const part of parts) {
    const index = part.indexOf('=');
    if (index === -1) continue;
    const key = part.slice(0, index);
    const value = part.slice(index + 1);
    if (key === 'row') row = value;
    else series.push({ key, value });
  }
  return { row, series };
}
