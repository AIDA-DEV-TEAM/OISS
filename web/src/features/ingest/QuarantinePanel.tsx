/**
 * Quarantine: the rows an error rule rejected, one line per row, with the rule
 * that rejected it and the offending value.
 *
 * Built from the error-severity findings, which carry the row reference, the
 * column and the value. Several rules can reject the same row, so findings are
 * folded by row rather than listed one per rule.
 */
import { useMemo } from 'react';

import type { ValidationFinding } from '@/api/client';
import { DataTable } from '@/components/DataTable';
import type { Column } from '@/components/DataTable';
import { Badge, Card, Figure } from '@/components/primitives';
import { EmptyState } from '@/components/states';
import { formatCount, parseRowRef } from '@/lib/format';

interface QuarantinedRow {
  row: string;
  series: Array<{ key: string; value: string }>;
  reasons: Array<{ rule: string; column: string | null; value: string | null }>;
}

export function QuarantinePanel({
  findings,
  quarantineTable,
  rowsQuarantined,
}: {
  findings: ValidationFinding[];
  quarantineTable?: string | null;
  rowsQuarantined: number;
}) {
  const rows = useMemo<QuarantinedRow[]>(() => {
    const byRow = new Map<string, QuarantinedRow>();
    for (const finding of findings) {
      if (finding.severity !== 'error') continue;
      const { row, series } = parseRowRef(finding.row_ref);
      const key = row ?? finding.row_ref ?? 'unknown';
      const existing = byRow.get(key) ?? { row: key, series, reasons: [] };
      existing.reasons.push({
        rule: finding.rule_code,
        column: finding.column_name ?? null,
        value: finding.observed_value ?? null,
      });
      byRow.set(key, existing);
    }
    return Array.from(byRow.values()).sort(
      (a, b) => Number(a.row) - Number(b.row) || a.row.localeCompare(b.row),
    );
  }, [findings]);

  const columns: Array<Column<QuarantinedRow>> = [
    {
      key: 'row',
      header: 'Row',
      numeric: true,
      width: '72px',
      render: (entry) => <Figure className="text-ink-muted">{entry.row}</Figure>,
    },
    {
      key: 'series',
      header: 'Row identity',
      render: (entry) =>
        entry.series.length === 0 ? (
          <span className="text-ink-subtle">—</span>
        ) : (
          <span className="flex flex-wrap gap-x-3 gap-y-0.5">
            {entry.series.map((part) => (
              <span key={part.key} className="whitespace-nowrap">
                <span className="text-ink-subtle">{part.key}</span>{' '}
                <span className="text-ink">{part.value}</span>
              </span>
            ))}
          </span>
        ),
    },
    {
      key: 'reasons',
      header: 'Rejected because',
      render: (entry) => (
        <span className="flex flex-wrap items-center gap-1.5">
          {entry.reasons.map((reason, index) => (
            <span key={`${reason.rule}-${index}`} className="inline-flex items-center gap-1">
              <Badge tone="error">{reason.rule}</Badge>
              {reason.column && (
                <span className="text-caption text-ink-muted">
                  {reason.column}
                  {reason.value !== null && (
                    <>
                      {' = '}
                      <code className="rounded bg-surface-alt px-1">{reason.value}</code>
                    </>
                  )}
                </span>
              )}
            </span>
          ))}
        </span>
      ),
    },
  ];

  return (
    <Card
      title="Quarantine"
      description="Rows an error rule held back. They are recorded, not discarded, and never reach staging or analytics."
      actions={
        rowsQuarantined > 0 ? (
          <Badge tone="error">
            <Figure>{formatCount(rowsQuarantined)}</Figure> rows
          </Badge>
        ) : (
          <Badge tone="success">No rows quarantined</Badge>
        )
      }
    >
      {rows.length === 0 ? (
        <EmptyState
          title="Nothing quarantined"
          detail="No row failed an error-severity rule, so every row reached staging. Warnings and informational findings do not quarantine a row."
        />
      ) : (
        <>
          <DataTable
            columns={columns}
            rows={rows}
            rowKey={(entry) => entry.row}
            compact
            maxHeight="320px"
            caption="Quarantined rows and the rules that rejected them"
          />
          {quarantineTable && (
            <p className="mt-2 text-caption text-ink-subtle">
              Stored as <code>{quarantineTable}</code>.
            </p>
          )}
        </>
      )}
    </Card>
  );
}
