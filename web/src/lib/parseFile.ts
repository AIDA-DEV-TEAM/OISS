/**
 * Client-side parsing for the schema preview.
 *
 * The backend's upload endpoint reports findings but not the file's shape, so
 * the preview (columns, inferred types, row count, first rows) is derived here
 * from the bytes the user actually chose. Nothing is invented: every value
 * shown comes from the file.
 *
 * CSV is parsed in-house — the publisher's quirks (UTF-8 BOM, CRLF, trailing
 * spaces in headers) are the same ones the backend readers absorb. Workbooks go
 * through SheetJS because .xlsx is a zip of XML.
 */
export type InferredType = 'integer' | 'decimal' | 'text' | 'date' | 'empty';

export interface ColumnProfile {
  name: string;
  type: InferredType;
  blankCount: number;
  sample: string | null;
}

export interface ParsedFile {
  columns: ColumnProfile[];
  rows: Array<Record<string, string>>;
  rowCount: number;
  /** Rows kept for the preview table; the full file is still uploaded. */
  previewRows: Array<Record<string, string>>;
  /** Set when a workbook was flattened to CSV for ingestion. */
  convertedFromSheet?: string;
  csvText: string;
}

const PREVIEW_ROWS = 25;

/** RFC 4180-ish: quoted fields, doubled quotes, embedded commas and newlines. */
export function parseCsv(text: string): { header: string[]; rows: string[][] } {
  const clean = text.replace(/^\uFEFF/, '');
  const rows: string[][] = [];
  let field = '';
  let row: string[] = [];
  let inQuotes = false;

  for (let index = 0; index < clean.length; index += 1) {
    const char = clean[index];
    if (inQuotes) {
      if (char === '"') {
        if (clean[index + 1] === '"') {
          field += '"';
          index += 1;
        } else {
          inQuotes = false;
        }
      } else {
        field += char;
      }
      continue;
    }
    if (char === '"') {
      inQuotes = true;
    } else if (char === ',') {
      row.push(field);
      field = '';
    } else if (char === '\n') {
      row.push(field);
      rows.push(row);
      row = [];
      field = '';
    } else if (char !== '\r') {
      field += char;
    }
  }
  if (field.length > 0 || row.length > 0) {
    row.push(field);
    rows.push(row);
  }

  const [header = [], ...body] = rows;
  // A trailing newline leaves one empty row; drop only genuinely empty ones.
  const kept = body.filter((line) => line.some((cell) => cell.trim() !== ''));
  return { header: header.map((name) => name.trim()), rows: kept };
}

const INTEGER_RE = /^-?\d+$/;
const DECIMAL_RE = /^-?\d*\.\d+$/;
// The agricultural year (2024-25) and ISO dates are both worth naming.
const DATE_RE = /^\d{4}-\d{2}(-\d{2})?$/;

function inferType(values: string[]): InferredType {
  const present = values.filter((value) => value.trim() !== '');
  if (present.length === 0) return 'empty';

  let integers = 0;
  let decimals = 0;
  let dates = 0;
  for (const value of present) {
    const trimmed = value.trim().replace(/,/g, '');
    if (DATE_RE.test(trimmed)) dates += 1;
    else if (INTEGER_RE.test(trimmed)) integers += 1;
    else if (DECIMAL_RE.test(trimmed)) decimals += 1;
  }
  // A column is called numeric only if nearly every present value parses; the
  // publisher's 'S' and '-' markers must not turn a text column into a number.
  const threshold = present.length * 0.95;
  if (dates >= threshold) return 'date';
  if (integers + decimals >= threshold) return decimals > 0 ? 'decimal' : 'integer';
  return 'text';
}

function profile(header: string[], rows: string[][]): ColumnProfile[] {
  return header.map((name, column) => {
    const values = rows.map((row) => row[column] ?? '');
    const present = values.filter((value) => value.trim() !== '');
    return {
      name,
      type: inferType(values),
      blankCount: values.length - present.length,
      sample: present[0] ?? null,
    };
  });
}

function toRecords(
  header: string[],
  rows: string[][],
): Array<Record<string, string>> {
  return rows.map((row) => {
    const record: Record<string, string> = {};
    header.forEach((name, index) => {
      record[name] = row[index] ?? '';
    });
    return record;
  });
}

function toCsvText(header: string[], rows: string[][]): string {
  const escape = (value: string) =>
    /[",\n\r]/.test(value) ? `"${value.replaceAll('"', '""')}"` : value;
  return [header, ...rows].map((row) => row.map(escape).join(',')).join('\n');
}

export function isWorkbook(file: File): boolean {
  return /\.(xlsx|xls|xlsm)$/i.test(file.name);
}

export async function parseFile(file: File): Promise<ParsedFile> {
  if (isWorkbook(file)) {
    // Loaded only when a workbook is actually chosen: the CSV path, which is
    // what the demo normally uses, never pays for the parser.
    const { read, utils } = await import('xlsx');
    const workbook = read(await file.arrayBuffer(), { type: 'array' });
    const sheetName = workbook.SheetNames[0];
    if (!sheetName) throw new Error('The workbook has no sheets.');
    const grid = utils.sheet_to_json<string[]>(workbook.Sheets[sheetName], {
      header: 1,
      raw: false,
      defval: '',
    });
    const [rawHeader = [], ...body] = grid;
    const header = rawHeader.map((name) => String(name ?? '').trim());
    const rows = body
      .map((row) => header.map((_, index) => String(row[index] ?? '')))
      .filter((row) => row.some((cell) => cell.trim() !== ''));
    return {
      columns: profile(header, rows),
      rows: toRecords(header, rows),
      rowCount: rows.length,
      previewRows: toRecords(header, rows.slice(0, PREVIEW_ROWS)),
      convertedFromSheet: sheetName,
      csvText: toCsvText(header, rows),
    };
  }

  const text = await file.text();
  const { header, rows } = parseCsv(text);
  return {
    columns: profile(header, rows),
    rows: toRecords(header, rows),
    rowCount: rows.length,
    previewRows: toRecords(header, rows.slice(0, PREVIEW_ROWS)),
    csvText: text,
  };
}
