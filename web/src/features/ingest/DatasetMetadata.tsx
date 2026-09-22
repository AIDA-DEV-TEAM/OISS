/**
 * Ingestion status and dataset metadata: name, source file, checksum, row
 * count, layer, load time and version id — the record a reviewer asks for when
 * they want to know exactly what was loaded.
 */
import type { DatasetVersion } from '@/api/client';
import { Badge, Card, DefinitionList, Figure } from '@/components/primitives';
import { ProvenanceNote } from '@/components/ProvenanceNote';
import { fileName, formatCount, formatTimestamp, shortHash } from '@/lib/format';

const LAYER_TONE: Record<string, 'neutral' | 'primary' | 'info'> = {
  raw: 'primary',
  reference: 'neutral',
  upload: 'info',
};

export function DatasetMetadata({
  dataset,
  actions,
}: {
  dataset: DatasetVersion;
  actions?: React.ReactNode;
}) {
  // data_origin is not on the version record; the generator version is what
  // marks a synthetic source, and it comes from the backend.
  const synthetic = Boolean(dataset.generator_version);

  return (
    <Card
      title="Dataset version"
      description="What was loaded, from where, and with what checksum."
      note={
        <ProvenanceNote
          className="mt-0.5"
          signals={{ dataOrigin: synthetic ? 'synthetic' : 'official' }}
        />
      }
      actions={
        <div className="flex items-center gap-2">
          <Badge tone={LAYER_TONE[dataset.layer] ?? 'neutral'}>{dataset.layer}</Badge>
          {actions}
        </div>
      }
    >
      <DefinitionList
        items={[
          { term: 'Dataset name', value: dataset.dataset_name },
          {
            term: 'Version id',
            value: <code className="text-caption">{dataset.dataset_version_id}</code>,
          },
          { term: 'Source type', value: dataset.source_type },
          {
            term: 'Rows read',
            value: <Figure>{formatCount(dataset.row_count)}</Figure>,
          },
          { term: 'Layer', value: dataset.layer },
          { term: 'Loaded at', value: <Figure>{formatTimestamp(dataset.loaded_at)}</Figure> },
          {
            term: 'SHA-256',
            value: (
              <code className="text-caption" title={dataset.sha256}>
                {shortHash(dataset.sha256)}
              </code>
            ),
          },
          {
            term: 'Generator version',
            value: dataset.generator_version ?? (
              <span className="text-ink-subtle">Not generated</span>
            ),
          },
          {
            term: 'Source file',
            value: (
              <span title={dataset.source_file}>{fileName(dataset.source_file)}</span>
            ),
            wide: true,
          },
        ]}
      />
    </Card>
  );
}
