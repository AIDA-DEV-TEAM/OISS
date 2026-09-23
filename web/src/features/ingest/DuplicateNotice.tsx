/**
 * The outcome when an uploaded file's contents are already in the system.
 *
 * Build data is immutable: a version id is a hash of the file's contents, so an
 * upload that produces an existing id is the same data arriving twice. Nothing
 * is re-read, re-promoted or overwritten. That is an ordinary, correct result,
 * so it reads as a statement of fact with a link to the version, not as an
 * error.
 */
import { Link } from 'react-router-dom';

import { Card } from '@/components/primitives';

export function DuplicateNotice({ versionId }: { versionId: string }) {
  return (
    <Card title="Already loaded">
      <p className="text-body text-ink">
        Already loaded as{' '}
        <Link
          to={`/lineage?version=${encodeURIComponent(versionId)}`}
          className="font-medium text-primary underline underline-offset-2"
        >
          {versionId}
        </Link>
        .
      </p>
      <p className="mt-2 text-caption text-ink-muted">
        This file&apos;s contents match a version already in the system, so nothing was
        re-read, re-promoted or overwritten. The upload is recorded against that
        version on Storage &amp; lineage, and its rows are untouched.
      </p>
    </Card>
  );
}
