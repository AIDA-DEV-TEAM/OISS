/**
 * Upload: drag-and-drop plus file picker, with the target dataset derived from
 * the file's own header and overridable.
 *
 * The backend validates an upload against a declared dataset schema, so
 * something has to say which dataset the file claims to be. That used to
 * default to whichever dataset sorted first, which silently pointed a price CSV
 * at the block land-use schema. The file's columns now choose, and when nothing
 * fits the panel says so instead of guessing.
 */
import { useRef, useState } from 'react';
import type { DragEvent } from 'react';

import type { IngestSchema } from '@/api/client';
import { Card, cn } from '@/components/primitives';
import { formatBytes } from '@/lib/format';
import { isWorkbook } from '@/lib/parseFile';
import type { SchemaMatch } from '@/lib/matchSchema';

const ACCEPT = '.csv,.xlsx,.xls,.xlsm';

export function UploadPanel({
  schemas,
  datasetName,
  match,
  parsed,
  onDatasetNameChange,
  onFile,
  file,
  busy,
}: {
  schemas: IngestSchema[];
  datasetName: string;
  /** What the file's header matched, or null when nothing fit well enough. */
  match: SchemaMatch | null;
  /** True once a file has been parsed, so the panel can explain the outcome. */
  parsed: boolean;
  onDatasetNameChange: (name: string) => void;
  onFile: (file: File) => void;
  file: File | null;
  busy: boolean;
}) {
  const [dragging, setDragging] = useState(false);
  const inputRef = useRef<HTMLInputElement>(null);

  const names = schemas.map((schema) => schema.dataset_name);
  const chosen = schemas.find((schema) => schema.dataset_name === datasetName);

  function handleDrop(event: DragEvent<HTMLDivElement>) {
    event.preventDefault();
    setDragging(false);
    const dropped = event.dataTransfer.files?.[0];
    if (dropped) onFile(dropped);
  }

  return (
    <Card
      title="Upload a file"
      description="Validated against a declared dataset schema through the same code path as the batch loader."
    >
      <div className="space-y-3">
        <div>
          <label
            htmlFor="dataset-name"
            className="block text-caption font-medium text-ink-muted"
          >
            Validate as
          </label>
          <select
            id="dataset-name"
            value={datasetName}
            onChange={(event) => onDatasetNameChange(event.target.value)}
            className="mt-1 w-full rounded border border-line bg-surface px-2 py-1.5 text-body text-ink"
          >
            <option value="">
              {parsed ? 'No matching dataset — choose one' : 'Detected from the file'}
            </option>
            {names.map((name) => (
              <option key={name} value={name}>
                {name}
              </option>
            ))}
          </select>
          {!parsed && (
            <p className="mt-1 text-caption text-ink-subtle">
              Chosen from the file&apos;s own columns once it is read. Override it here if the
              file is an instance of a different dataset.
            </p>
          )}
          {parsed && match && (
            <p className="mt-1 text-caption text-ink-subtle">
              Matched on the file&apos;s columns
              {chosen ? ` · expects ${chosen.source_type.toUpperCase()}` : ''}.
              {match.missing.length > 0 &&
                ` ${match.missing.length} declared column(s) still missing.`}
            </p>
          )}
          {parsed && !match && (
            <p className="mt-1 border-l-rule border-l-warning bg-warning-bg px-3 py-2 text-caption text-ink-muted">
              This file&apos;s columns do not match any declared dataset. Pick the dataset it is
              meant to be and the validator will report exactly which columns differ.
            </p>
          )}
        </div>

        <div
          onDragOver={(event) => {
            event.preventDefault();
            setDragging(true);
          }}
          onDragLeave={() => setDragging(false)}
          onDrop={handleDrop}
          className={cn(
            'rounded border-2 border-dashed px-card py-6 text-center transition-colors duration-state',
            dragging ? 'border-primary bg-primary-subtle' : 'border-line-strong bg-surface-alt',
          )}
        >
          <p className="text-body text-ink">Drop a CSV or Excel file here</p>
          <p className="mt-1 text-caption text-ink-muted">or</p>
          <button
            type="button"
            disabled={busy}
            onClick={() => inputRef.current?.click()}
            className="mt-2 rounded border border-primary bg-primary px-3 py-1.5 text-body font-medium text-white transition-colors duration-state hover:bg-primary-hover disabled:cursor-not-allowed disabled:opacity-60"
          >
            Choose a file
          </button>
          <input
            ref={inputRef}
            type="file"
            accept={ACCEPT}
            className="sr-only"
            onChange={(event) => {
              const chosen = event.target.files?.[0];
              if (chosen) onFile(chosen);
              event.target.value = '';
            }}
          />
          {file && (
            <p className="mt-3 text-caption text-ink-muted">
              {file.name} · {formatBytes(file.size)}
              {isWorkbook(file) && ' · workbook'}
            </p>
          )}
        </div>
      </div>
    </Card>
  );
}
