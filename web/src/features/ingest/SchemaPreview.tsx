/**
 * Schema preview: detected columns, inferred types, row count and first rows.
 *
 * Read from the chosen file itself, before it is sent. Types are inferred from
 * the values present, so a column of dashes and 'S' markers stays text rather
 * than pretending to be numeric.
 */
import type { ParsedFile } from '@/lib/parseFile';
import { Badge, Card, Figure } from '@/components/primitives';
import { DataTable } from '@/components/DataTable';
import type { Column } from '@/components/DataTable';
import { formatCount } from '@/lib/format';

const TYPE_LABEL: Record<string, string> = {
  integer: 'Integer',
  decimal: 'Decimal',
  date: 'Date / year',
  text: 'Text',
  empty: 'Empty',
};

export function SchemaPreview({ parsed }: { parsed: ParsedFile }) {
  const columns: Array<Column<ParsedFile['columns'][number]>> = [
    { key: 'name', header: 'Column', render: (row) => <span className="font-medium">{row.name}</span> },
    {
      key: 'type',
      header: 'Inferred type',
      render: (row) => <Badge tone={row.type === 'empty' ? 'warning' : 'neutral'}>{TYPE_LABEL[row.type]}</Badge>,
    },
    {
      key: 'blank',
      header: 'Blank',
      numeric: true,
      render: (row) => <Figure>{formatCount(row.blankCount)}</Figure>,
    },
    {
      key: 'sample',
      header: 'First value',
      render: (row) =>
        row.sample === null ? (
          <span className="text-ink-subtle">—</span>
        ) : (
          <span className="text-ink-muted">{row.sample}</span>
        ),
    },
  ];

  const previewColumns: Array<Column<Record<string, string>>> = parsed.columns.map(
    (column) => ({
      key: column.name,
      header: column.name,
      numeric: column.type === 'integer' || column.type === 'decimal',
      render: (row) => {
        const value = row[column.name];
        return value === '' ? (
          <span className="text-ink-subtle">—</span>
        ) : column.type === 'integer' || column.type === 'decimal' ? (
          <Figure>{value}</Figure>
        ) : (
          value
        );
      },
    }),
  );

  return (
    <div className="space-y-4">
      <Card
        title="Detected schema"
        description={`${parsed.columns.length} columns, ${formatCount(parsed.rowCount)} data rows`}
        actions={
          parsed.convertedFromSheet ? (
            <Badge tone="warning" title="The backend readers take CSV and Stata; the sheet was flattened to CSV before upload.">
              Converted from sheet “{parsed.convertedFromSheet}”
            </Badge>
          ) : undefined
        }
      >
        <DataTable
          columns={columns}
          rows={parsed.columns}
          rowKey={(row) => row.name}
          compact
          caption="Detected columns and inferred types"
        />
      </Card>

      <Card
        title="First rows"
        description={`Showing ${formatCount(parsed.previewRows.length)} of ${formatCount(parsed.rowCount)} rows as read from the file`}
      >
        <DataTable
          columns={previewColumns}
          rows={parsed.previewRows}
          rowKey={(_, index) => String(index)}
          compact
          maxHeight="360px"
          caption="First rows of the uploaded file"
          emptyMessage="The file has no data rows."
        />
      </Card>
    </div>
  );
}
