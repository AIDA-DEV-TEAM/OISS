/**
 * The two things an upload has to declare, and the one thing it must not do
 * twice.
 *
 * A file with no registered schema has no declared origin either, so the
 * uploader states it — the system never guesses whether data is official or
 * synthetic. And a file whose contents are already loaded is a duplicate, not
 * an error: build data is immutable and the screen has to say so.
 */
import { cleanup, fireEvent, render, screen } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { afterEach, describe, expect, it, vi } from 'vitest';

import type { IngestSchema } from '@/api/client';
import { DuplicateNotice } from '@/features/ingest/DuplicateNotice';
import { UploadPanel } from '@/features/ingest/UploadPanel';
import { scoreSchema } from '@/lib/matchSchema';

const SCHEMAS: IngestSchema[] = [
  {
    dataset_name: 'earas_2022_23_block_land_use',
    source_type: 'stata',
    expected_columns: ['district', 'block', 'land_use_class', 'area_ha'],
  },
];

const MATCH = scoreSchema(SCHEMAS[0].expected_columns, SCHEMAS[0]);

function panel(props: Partial<React.ComponentProps<typeof UploadPanel>> = {}) {
  return render(
    <UploadPanel
      schemas={SCHEMAS}
      datasetName=""
      match={null}
      parsed
      dataOrigin=""
      onDataOriginChange={() => {}}
      onDatasetNameChange={() => {}}
      onFile={() => {}}
      file={null}
      busy={false}
      {...props}
    />,
  );
}

afterEach(() => {
  cleanup();
});

describe('declared data origin', () => {
  it('asks for an origin when the file matches no registered schema', () => {
    panel();
    const select = screen.getByLabelText(/Data origin/);
    expect(select).toBeTruthy();
    // No default: the uploader has to choose, because the backend refuses the
    // upload with 422 rather than assuming one.
    expect((select as HTMLSelectElement).value).toBe('');
    const options = Array.from((select as HTMLSelectElement).options).map((o) => o.value);
    expect(options).toEqual(['', 'official', 'synthetic']);
  });

  it('explains what each option means', () => {
    panel();
    const help = screen.getByText(/Official: published or supplied by a statistical authority/);
    expect(help.textContent).toMatch(/Synthetic: generated for demonstration/);
    expect(screen.getByLabelText(/Data origin/).getAttribute('aria-describedby')).toBe(
      help.getAttribute('id'),
    );
  });

  it('does not ask when the file matches a registered dataset', () => {
    panel({ datasetName: SCHEMAS[0].dataset_name, match: MATCH });
    // A registered dataset declares its own origin; asking again would invite
    // an upload to contradict the dataset definition.
    expect(screen.queryByLabelText(/Data origin/)).toBeNull();
  });

  it('does not ask before a file has been read', () => {
    panel({ parsed: false });
    expect(screen.queryByLabelText(/Data origin/)).toBeNull();
  });

  it('reports the chosen origin', () => {
    const onChange = vi.fn();
    panel({ onDataOriginChange: onChange });
    fireEvent.change(screen.getByLabelText(/Data origin/), {
      target: { value: 'synthetic' },
    });
    expect(onChange).toHaveBeenCalledWith('synthetic');
  });
});

describe('duplicate upload', () => {
  it('states the existing version and links to it on Storage & lineage', () => {
    const versionId = 'earas_2023_24_district_paddy@5e8bdea5ea67';
    render(
      <MemoryRouter future={{ v7_startTransition: true, v7_relativeSplatPath: true }}>
        <DuplicateNotice versionId={versionId} />
      </MemoryRouter>,
    );
    const link = screen.getByRole('link', { name: versionId });
    expect(link.getAttribute('href')).toBe(
      `/lineage?version=${encodeURIComponent(versionId)}`,
    );
    expect(screen.getByText(/Already loaded as/)).toBeTruthy();
    // Not an error: nothing failed, the data was simply already there.
    expect(screen.queryByText(/error/i)).toBeNull();
    expect(screen.queryByText(/failed/i)).toBeNull();
  });
});
