import { Figure, cn } from '@/components/primitives';

interface RecordsTableProps {
  records: Array<Record<string, unknown>>;
}

/** The underlying fact rows behind an answer, each with its dataset version. */
export function RecordsTable({ records }: RecordsTableProps) {
  const columns = Object.keys(records[0] ?? {});
  if (columns.length === 0) return null;

  return (
    <div className="mt-3 overflow-x-auto rounded border border-line">
      <table className="w-full text-left text-body">
        <caption className="sr-only">Records supporting the answer</caption>
        <thead className="border-b border-line bg-surface-alt text-caption font-medium uppercase tracking-header text-ink-subtle">
          <tr>
            {columns.map((column) => (
              <th key={column} scope="col" className="whitespace-nowrap px-3 py-2">
                {column.replaceAll('_', ' ')}
              </th>
            ))}
          </tr>
        </thead>
        <tbody className="divide-y divide-line bg-surface">
          {records.map((record, index) => (
            // Fact rows carry no single id column across relations; their
            // position in this fixed, ordered preview is stable.
            <tr key={index} className="hover:bg-surface-alt">
              {columns.map((column) => {
                const value = record[column];
                const numeric = typeof value === 'number';
                return (
                  <td
                    key={column}
                    className={cn('whitespace-nowrap px-3 py-2 text-ink', numeric && 'text-right')}
                  >
                    {value === null || value === undefined ? (
                      <span className="text-ink-subtle" title="No value recorded">
                        —
                      </span>
                    ) : numeric ? (
                      <Figure>{value.toLocaleString('en-IN')}</Figure>
                    ) : (
                      String(value)
                    )}
                  </td>
                );
              })}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
