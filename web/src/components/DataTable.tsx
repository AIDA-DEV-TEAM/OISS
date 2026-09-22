/**
 * Keyboard-navigable data table — DESIGN.md §4.
 *
 * 36px rows (32px compact), header on surface-alt with a bottom border,
 * right-aligned numerics, no zebra striping, hover highlight, sticky header on
 * long grids. Rows are reachable with Tab and activate on Enter or Space when
 * the table is interactive.
 */
import type { KeyboardEvent, ReactNode } from 'react';

import { cn } from '@/components/primitives';

export interface Column<T> {
  key: string;
  header: ReactNode;
  /** Numeric columns are right-aligned and rendered with tabular figures. */
  numeric?: boolean;
  width?: string;
  render: (row: T) => ReactNode;
}

interface DataTableProps<T> {
  columns: Array<Column<T>>;
  rows: T[];
  rowKey: (row: T, index: number) => string;
  compact?: boolean;
  /** Adds sticky header and a scroll container. */
  maxHeight?: string;
  onRowActivate?: (row: T) => void;
  isRowSelected?: (row: T) => boolean;
  caption?: string;
  emptyMessage?: string;
}

export function DataTable<T>({
  columns,
  rows,
  rowKey,
  compact = false,
  maxHeight,
  onRowActivate,
  isRowSelected,
  caption,
  emptyMessage,
}: DataTableProps<T>) {
  const interactive = Boolean(onRowActivate);

  function handleKey(event: KeyboardEvent<HTMLTableRowElement>, row: T) {
    if (!onRowActivate) return;
    if (event.key === 'Enter' || event.key === ' ') {
      event.preventDefault();
      onRowActivate(row);
    }
  }

  if (rows.length === 0 && emptyMessage) {
    return (
      <p className="px-3 py-6 text-center text-body text-ink-muted">{emptyMessage}</p>
    );
  }

  return (
    <div
      className={cn('overflow-auto rounded border border-line', maxHeight && 'relative')}
      style={maxHeight ? { maxHeight } : undefined}
    >
      <table className="w-full border-collapse text-body">
        {caption && <caption className="sr-only">{caption}</caption>}
        <thead>
          <tr>
            {columns.map((column) => (
              <th
                key={column.key}
                scope="col"
                style={column.width ? { width: column.width } : undefined}
                className={cn(
                  'border-b border-line bg-surface-alt px-3 py-2 text-caption font-medium text-ink-muted',
                  column.numeric ? 'text-right' : 'text-left',
                  maxHeight && 'sticky top-0 z-10',
                )}
              >
                {column.header}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {rows.map((row, index) => {
            const selected = isRowSelected?.(row) ?? false;
            return (
              <tr
                key={rowKey(row, index)}
                tabIndex={interactive ? 0 : undefined}
                role={interactive ? 'button' : undefined}
                onClick={interactive ? () => onRowActivate?.(row) : undefined}
                onKeyDown={interactive ? (event) => handleKey(event, row) : undefined}
                className={cn(
                  'border-b border-line last:border-b-0 transition-colors duration-state',
                  compact ? 'h-row-compact' : 'h-row',
                  selected ? 'bg-primary-subtle' : 'bg-surface hover:bg-surface-alt',
                  interactive && 'cursor-pointer',
                )}
              >
                {columns.map((column) => (
                  <td
                    key={column.key}
                    className={cn(
                      'px-3 align-middle text-ink',
                      column.numeric ? 'text-right' : 'text-left',
                    )}
                  >
                    {column.render(row)}
                  </td>
                ))}
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}
