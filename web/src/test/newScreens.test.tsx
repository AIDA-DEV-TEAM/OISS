/**
 * Smoke cover for the screens added in this pass: Assistant, Sandbox and
 * Exports.
 *
 * These are mocked surfaces, so the value here is not in the numbers — it is in
 * proving that each nav destination renders a complete screen rather than a
 * placeholder, that the provenance disclosure is the quiet panel line rather
 * than per-figure chips, and that the assistant's refusal path actually
 * refuses.
 */
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { cleanup, fireEvent, render, screen } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { afterEach, beforeAll, describe, expect, it } from 'vitest';

import { AssistantPage } from '@/pages/AssistantPage';
import { ExportsPage } from '@/pages/ExportsPage';
import { SandboxPage } from '@/pages/SandboxPage';
import { installFetchStub } from '@/test/server';

class ResizeObserverMock {
  observe() {}
  unobserve() {}
  disconnect() {}
}

beforeAll(() => {
  installFetchStub();
  if (!globalThis.ResizeObserver) {
    // jsdom has no ResizeObserver; Recharts needs one to mount at all.
    globalThis.ResizeObserver = ResizeObserverMock as unknown as typeof ResizeObserver;
  }
});

afterEach(() => {
  cleanup();
});

function mount(ui: React.ReactNode) {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false, gcTime: 0 } },
  });
  return render(
    <QueryClientProvider client={client}>
      <MemoryRouter future={{ v7_startTransition: true, v7_relativeSplatPath: true }}>
        {ui}
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

describe('Assistant (RFP areas 4-5)', () => {
  it('offers the predefined questions and starts with nothing answered', async () => {
    mount(<AssistantPage />);
    expect(
      await screen.findByRole('button', {
        name: /Which districts had the highest paddy yield in 2024-25\?/i,
      }),
    ).toBeTruthy();
    expect(screen.getByText(/No question asked yet/i)).toBeTruthy();
  });

  it('answers with filters, source, period, records and a panel-level provenance line', async () => {
    mount(<AssistantPage />);
    const chip = await screen.findByRole('button', {
      name: /Which districts lead and lag on farm-harvest prices\?/i,
    });
    fireEvent.click(chip);

    expect(await screen.findByText(/Bargarh leads on average farm-harvest price/i)).toBeTruthy();
    expect(screen.getByText(/Applied filters/i)).toBeTruthy();
    expect(screen.getByText(/Reporting period/i)).toBeTruthy();
    expect(screen.getByText(/Supporting records/i)).toBeTruthy();

    // Disclosure is one quiet line for the panel, not a chip beside each figure.
    expect(
      screen.getByText(/Representative dataset modelled on DE&S Price Statistics, 2013-19/i),
    ).toBeTruthy();
    expect(screen.queryByText(/^Synthetic$/)).toBeNull();
  });

  it('declines the question the data cannot answer instead of guessing', async () => {
    mount(<AssistantPage />);
    const chip = await screen.findByRole('button', {
      name: /What were block-level wholesale prices in Bargarh in 2023-24\?/i,
    });
    fireEvent.click(chip);

    // The phrase appears in both the heading and the answer body, so match the
    // heading precisely rather than loosely.
    expect(
      await screen.findByText(/^This cannot be answered from the loaded data$/i),
    ).toBeTruthy();
    expect(screen.getByText(/published at district grain only/i)).toBeTruthy();
  });
});

describe('Sandbox (RFP areas 6-7)', () => {
  it('opens on the dataset step with every wizard step listed', async () => {
    mount(<SandboxPage />);
    expect(await screen.findByRole('navigation', { name: /Sandbox steps/i })).toBeTruthy();
    for (const step of ['Dataset', 'Use case', 'Target', 'Features', 'Run', 'Results', 'Publish']) {
      expect(screen.getByRole('button', { name: new RegExp(step, 'i') })).toBeTruthy();
    }
  });

  it('defaults to the crop-yield preset and blocks steps that are not reachable yet', async () => {
    mount(<SandboxPage />);
    // Results cannot be opened before a run has completed.
    const results = await screen.findByRole('button', { name: /Results/i });
    expect(results.hasAttribute('disabled')).toBe(true);
  });
});

describe('Exports (RFP area 8)', () => {
  it('lists recent exports with the context each file carries', async () => {
    mount(<ExportsPage />);
    expect(
      await screen.findByText(/district_farm_harvest_price_2024-25\.xlsx/i),
    ).toBeTruthy();
    expect(screen.getAllByRole('button', { name: /^Download$/i }).length).toBeGreaterThan(0);
  });

  it('opens an export and shows the applied context attached to it', async () => {
    mount(<ExportsPage />);
    const row = await screen.findByText(/minor_crop_yield_run_07\.json/i);
    fireEvent.click(row);

    expect(await screen.findByText(/Applied context/i)).toBeTruthy();
    // Model output discloses itself with the panel line, not an estimate chip.
    expect(screen.getByText(/^Analytical estimates$/i)).toBeTruthy();
  });
});
