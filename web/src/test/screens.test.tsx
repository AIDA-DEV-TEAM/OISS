/**
 * Render smoke tests for the two delivered screens.
 *
 * They mount the real components against payloads captured from the running
 * backend, so a white screen, a missing field or a broken provenance rule
 * fails here rather than during a demo.
 */
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { cleanup, render, screen, waitFor, within } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { afterEach, beforeAll, beforeEach, describe, expect, it } from 'vitest';

import { IngestPage } from '@/pages/IngestPage';
import { LineagePage } from '@/pages/LineagePage';
import { installFetchStub } from '@/test/server';

function mount(ui: React.ReactElement) {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false, gcTime: 0 } },
  });
  return render(
    <QueryClientProvider client={client}>
      <MemoryRouter
        future={{ v7_startTransition: true, v7_relativeSplatPath: true }}
      >
        {ui}
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

beforeAll(() => {
  installFetchStub();
});

beforeEach(() => {
  installFetchStub();
});

// Auto-cleanup only registers itself when the runner exposes globals, which
// this config does not; without it each test would inherit the previous DOM.
afterEach(() => {
  cleanup();
});

describe('Ingest and validate', () => {
  it('lists the bundled datasets with their real row counts', async () => {
    mount(<IngestPage />);
    expect(await screen.findByText('Bundled datasets')).toBeTruthy();
    // 1,032 rows is what the 2022-23 block paddy file actually holds.
    await waitFor(() => expect(screen.getAllByText('1,032').length).toBeGreaterThan(0));
    expect(screen.getByText('earas_2022_23_block_paddy')).toBeTruthy();
  });

  it('shows the dataset version record including its checksum', async () => {
    mount(<IngestPage />);
    expect(await screen.findByText('Dataset version')).toBeTruthy();
    await waitFor(() => expect(screen.getByText('SHA-256')).toBeTruthy());
    expect(screen.getByText('Rows read')).toBeTruthy();
  });

  it('defaults the findings view to errors and warnings only', async () => {
    mount(<IngestPage />);
    const heading = await screen.findByText('Validation findings');
    expect(heading).toBeTruthy();

    // The two warning rules for this dataset are listed by default.
    await waitFor(() => expect(screen.getByText('Missing value')).toBeTruthy());
    expect(screen.getByText('Unknown block')).toBeTruthy();

    // The informational rule is not, until the toggle is used.
    expect(screen.queryByText('Structurally absent')).toBeNull();
  });

  it('puts the structurally-absent findings behind a visible, labelled toggle', async () => {
    mount(<IngestPage />);
    await screen.findByText('Validation findings');
    const toggle = await waitFor(() =>
      screen.getByLabelText(/Also show informational findings/i),
    );
    expect(toggle).toBeTruthy();

    // The distinction is stated on screen, not left to the reader.
    expect(
      screen.getByText(/combinations that do not exist/i),
    ).toBeTruthy();
  });

  it('reports an empty quarantine as clean rather than as a failure', async () => {
    mount(<IngestPage />);
    expect(await screen.findByText('Quarantine')).toBeTruthy();
    await waitFor(() => expect(screen.getByText('No rows quarantined')).toBeTruthy());
    expect(screen.getByText('Nothing quarantined')).toBeTruthy();
  });
});

describe('Storage and lineage', () => {
  it('shows all four storage layers with their row counts', async () => {
    mount(<LineagePage />);
    expect(await screen.findByText('Storage layers')).toBeTruthy();
    await waitFor(() => expect(screen.getByText(/1\. Raw \/ landing/)).toBeTruthy());
    expect(screen.getByText(/2\. Validation \/ quarantine/)).toBeTruthy();
    expect(screen.getByText(/3\. Cleansed \/ staging/)).toBeTruthy();
    expect(screen.getByText(/4\. Analytics-ready/)).toBeTruthy();

    // 1,032 source rows become 3,096 staged rows: one per measure.
    expect(screen.getAllByText('3,096').length).toBeGreaterThan(0);
  });

  it('explains what happened between the layers', async () => {
    mount(<LineagePage />);
    await screen.findByText('Storage layers');
    await waitFor(() =>
      expect(screen.getByText(/split into 3 rows, one per measure/i)).toBeTruthy(),
    );
  });

  it('renders the lineage graph with every hop the backend recorded', async () => {
    mount(<LineagePage />);
    const graph = await waitFor(() =>
      screen.getByRole('img', { name: /Lineage from source file/i }),
    );
    const text = graph.textContent ?? '';
    for (const edge of ['extract', 'transform', 'load', 'publish', 'aggregate']) {
      expect(text).toContain(edge);
    }
  });

  it('makes the 2022-23 paddy block rollup visible and explains it', async () => {
    mount(<LineagePage />);
    await waitFor(() => expect(screen.getByText('Lineage')).toBeTruthy());
    // The panel-level provenance line and the explanation both appear, because
    // a reviewer will ask where district paddy came from for a year published
    // block-wise only.
    await waitFor(() =>
      expect(
        screen.getAllByText('District figures aggregated from block-level data').length,
      ).toBeGreaterThan(0),
    );
    expect(
      screen.getByText(/summed to district grain and the yield recomputed/i),
    ).toBeTruthy();
  });

  it('shows the validation summary for the selected version', async () => {
    mount(<LineagePage />);
    const panel = await waitFor(() => screen.getByText('Validation summary'));
    expect(panel).toBeTruthy();
    await waitFor(() => expect(screen.getByText('Unknown block')).toBeTruthy());
  });

  it('shows the full checksum in the version record', async () => {
    mount(<LineagePage />);
    const card = await waitFor(() => screen.getByText('Version record'));
    expect(card).toBeTruthy();
    await waitFor(() =>
      expect(
        screen.getByText(
          '33743b3c4831b2a8ebb46f9e3cfa738adfb047f7410acde927f2a5a661259952',
        ),
      ).toBeTruthy(),
    );
  });
});

describe('Design conformance', () => {
  it('renders figures with tabular numerals', async () => {
    const { container } = mount(<LineagePage />);
    await screen.findByText('Storage layers');
    await waitFor(() =>
      expect(container.querySelectorAll('.figure').length).toBeGreaterThan(0),
    );
  });

  it('keeps tables keyboard reachable', async () => {
    mount(<LineagePage />);
    const table = await waitFor(() =>
      screen.getByRole('table', { name: /Dataset versions/i }),
    );
    const rows = within(table).getAllByRole('button');
    expect(rows.length).toBeGreaterThan(0);
    // Every interactive row is in the tab order.
    expect(rows.every((row) => row.getAttribute('tabindex') === '0')).toBe(true);
  });
});
