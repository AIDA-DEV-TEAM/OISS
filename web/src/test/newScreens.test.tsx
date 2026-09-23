/**
 * Smoke cover for the screens added in this pass: Assistant, Sandbox and
 * Exports.
 *
 * The stub answers from payloads captured from the backend, so the value here
 * is in proving that each nav destination renders a complete screen, that
 * the provenance disclosure is the quiet panel line rather than per-figure
 * chips, and that the assistant's refusal path actually refuses.
 */
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { afterEach, beforeAll, describe, expect, it } from 'vitest';

import { AssistantPage } from '@/pages/AssistantPage';
import { ExportModal } from '@/components/ExportModal';
import { ExportsPage } from '@/pages/ExportsPage';
import { SandboxPage } from '@/pages/SandboxPage';
import sandbox from '@/test/fixtures/sandbox.json';
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

const MSP_QUESTION = 'What is the average price of paddy in Cuttack?';

async function askQuestion(question: string) {
  const box = await screen.findByLabelText(/Your question/i);
  fireEvent.change(box, { target: { value: question } });
  fireEvent.click(screen.getByRole('button', { name: /^Ask$/ }));
}

describe('Assistant (RFP area 5)', () => {
  it('leads with a free-text question box, with starters that fill it', async () => {
    mount(<AssistantPage />);
    const box = (await screen.findByLabelText(/Your question/i)) as HTMLTextAreaElement;
    expect(screen.getByText(/No question asked yet/i)).toBeTruthy();

    const chip = await screen.findByRole('button', {
      name: /Which districts had the highest paddy yield in 2024-25\?/i,
    });
    fireEvent.click(chip);

    // A starter fills the box; it does not ask on its own.
    expect(box.value).toBe('Which districts had the highest paddy yield in 2024-25?');
    expect(screen.getByText(/No question asked yet/i)).toBeTruthy();
    expect(screen.getByText(/Declining accurately is intended behaviour/i)).toBeTruthy();
  });

  it('answers with filters, source, period, records, caveats and the cache marker', async () => {
    mount(<AssistantPage />);
    await askQuestion(MSP_QUESTION);

    expect(
      await screen.findByText(/official farm-harvest price of paddy in Cuttack rose/i),
    ).toBeTruthy();
    // Filters in display names, with the code beside them.
    expect(screen.getAllByText(/District: Cuttack \(OD07\)/).length).toBeGreaterThan(0);
    expect(screen.getByText(/Reporting period/i).nextElementSibling?.textContent).toBe(
      '2013-14 to 2018-19',
    );
    expect(screen.getByText(/Source dataset/i)).toBeTruthy();
    expect(screen.getByText(/Supporting records/i)).toBeTruthy();
    expect(screen.getByText(/Served from cache/i)).toBeTruthy();
    expect(screen.getByRole('list', { name: /Caveats/i }).textContent).toMatch(
      /Minimum Support/i,
    );
  });

  it('shows how the question was read', async () => {
    mount(<AssistantPage />);
    await askQuestion(MSP_QUESTION);

    const summary = await screen.findByText(/How this was answered/i);
    fireEvent.click(summary);
    const details = summary.closest('details');
    expect(details?.textContent).toMatch(/Average price \(Rs\/quintal\)/);
    expect(details?.textContent).toMatch(/Agricultural year/);
    expect(details?.textContent).toMatch(/Data origin: official/);
    expect(details?.textContent).toMatch(/Recorded response \(fixture\)/);
  });

  it('declines the question the data cannot answer, naming why', async () => {
    mount(<AssistantPage />);
    await askQuestion('What were block-level wholesale prices in Bargarh in 2023-24?');

    expect(
      await screen.findByText(/^This cannot be answered from the loaded data$/i),
    ).toBeTruthy();
    expect(screen.getByText(/district grain only/i)).toBeTruthy();
    expect(screen.getByText(/Declining here is the correct answer/i)).toBeTruthy();
  });

  it('says plainly when a new question cannot be interpreted without a model', async () => {
    mount(<AssistantPage />);
    await askQuestion('How much rain fell in Puri last year?');

    expect(
      await screen.findByText(/The question could not be interpreted right now/i),
    ).toBeTruthy();
    expect(screen.queryByText(/Served from cache/i)).toBeNull();
  });

  it('keeps the input editable and shows progress while an answer is on its way', async () => {
    const stubbed = globalThis.fetch;
    let release: () => void = () => {};
    const held = new Promise<void>((resolve) => {
      release = resolve;
    });
    globalThis.fetch = (async (input: RequestInfo | URL, init?: RequestInit) => {
      if (String(input).includes('/assistant/ask')) await held;
      return stubbed(input, init);
    }) as typeof fetch;

    try {
      mount(<AssistantPage />);
      await askQuestion(MSP_QUESTION);

      expect(await screen.findByText(/Reading the question, running the query/i)).toBeTruthy();
      const box = screen.getByLabelText(/Your question/i) as HTMLTextAreaElement;
      expect(box.disabled).toBe(false);
      fireEvent.change(box, { target: { value: 'A follow-up, typed while waiting' } });
      expect(box.value).toBe('A follow-up, typed while waiting');

      release();
      expect(
        await screen.findByText(/official farm-harvest price of paddy in Cuttack rose/i),
      ).toBeTruthy();
    } finally {
      globalThis.fetch = stubbed;
    }
  });
});

describe('Sandbox (RFP areas 6-7)', () => {
  /** Dataset → Use case → Model configuration, then the bottom bar's Run. */
  async function runFromTheWizard() {
    for (let i = 0; i < 2; i += 1) {
      const next = await screen.findByRole('button', { name: /^Continue$/ });
      await waitFor(() => expect(next.hasAttribute('disabled')).toBe(false));
      fireEvent.click(next);
    }
    const run = screen.getAllByRole('button', { name: /^Run$/ }).at(-1) as HTMLElement;
    await waitFor(() => expect(run.hasAttribute('disabled')).toBe(false));
    fireEvent.click(run);
  }

  it('lists only real choices: no target, features, split or horizon steps', async () => {
    mount(<SandboxPage />);
    const nav = await screen.findByRole('navigation', { name: /Sandbox steps/i });
    const steps = Array.from(nav.querySelectorAll('button')).map((b) =>
      (b.textContent ?? '').replace(/^\d+\.\s*/, ''),
    );
    expect(steps).toEqual([
      'Dataset',
      'Use case',
      'Model configuration',
      'Run',
      'Results',
      'Save version',
      'Publish',
    ]);
  });

  it('disables each incompatible dataset and names the fields it is missing', async () => {
    mount(<SandboxPage />);
    const price = (await screen.findByText('price_statistics_2020')).closest('label');
    expect(price?.querySelector('input')?.hasAttribute('disabled')).toBe(true);
    expect(price?.textContent).toMatch(/cannot run: missing season .*area_ha/);

    const ayp = screen.getByText('earas_2024_25_district_crop_ayp').closest('label');
    expect(ayp?.querySelector('input')?.hasAttribute('disabled')).toBe(false);
    // Out-of-domain combinations are counted with their reason, not dropped silently.
    expect(ayp?.textContent).toMatch(/536 of 622 .* within the model's input domains/);
    expect(ayp?.textContent).toMatch(/crop not in the model's minor_crops \(GET \/metadata\)/);
    // Row counts come from the backend's query.
    expect(ayp?.textContent).toMatch(/rows in this system/);
  });

  it('shows the use case read-only and the model configuration with its sources', async () => {
    mount(<SandboxPage />);
    const next = await screen.findByRole('button', { name: /^Continue$/ });
    await waitFor(() => expect(next.hasAttribute('disabled')).toBe(false));
    fireEvent.click(next);
    expect(await screen.findByText(/one model \(Tuned Gradient Boosting Regressor\)/)).toBeTruthy();
    // A fixed value, not a selector with one option.
    expect(screen.queryAllByRole('radio')).toHaveLength(0);

    fireEvent.click(screen.getByRole('button', { name: /^Continue$/ }));
    expect(await screen.findByText('Yield_rate_qtl_per_ha')).toBeTruthy();
    const version = screen.getByText('Model version').closest('div');
    expect(version?.textContent).toMatch(/not stated by the model service/);
    const period = screen.getByText('Training period').closest('div');
    expect(period?.textContent).toMatch(/not stated by the model service/);
    expect(screen.getAllByText(/Stated by GET \/health/).length).toBe(2);
    expect(screen.getByText(/Stated by GET \/openapi\.json/)).toBeTruthy();
    expect(screen.getByText(/The values the model accepts, not features/)).toBeTruthy();
  });

  it('says the run blocks until it ends, not that it reports progress', async () => {
    mount(<SandboxPage />);
    await screen.findByRole('navigation', { name: /Sandbox steps/i });
    expect(screen.queryByText(/reports real progress/i)).toBeNull();
    const results = screen.getByRole('button', { name: /Results/i });
    expect(results.hasAttribute('disabled')).toBe(true);
  });

  it('keeps every estimate when the evaluation fails, and labels the comparison honestly', async () => {
    mount(<SandboxPage />);
    await runFromTheWizard();

    const message = await screen.findByText(/Run complete with warnings: 536 estimates/i);
    expect(message.closest('[role="status"]')).toBeTruthy();
    expect(message.textContent).toMatch(/86 of the dataset's 622 combinations were outside/);
    expect(message.textContent).toMatch(
      /GET \/actual-vs-predicted\?limit=200 returned 422: query\.limit/,
    );

    const next = screen.getByRole('button', { name: /^Continue$/ });
    await waitFor(() => expect(next.hasAttribute('disabled')).toBe(false));
    fireEvent.click(next);

    expect(
      await screen.findByText(/part of the model's evaluation could not be produced/i),
    ).toBeTruthy();
    // The model has no stated training period: an estimate, never a forecast.
    expect(screen.getByText('Model estimate vs published 2024-25 actual')).toBeTruthy();
    expect(screen.queryByText(/forecast/i)).toBeNull();
    expect(screen.queryByText(/held-out evaluation/i)).toBeNull();
    // The service's evaluation is attributed to the service.
    expect(screen.getByText(/The model service's evaluation of its model/)).toBeTruthy();
    // No held-out records: the metrics are a dash, and each section says why.
    expect(screen.getAllByText('—').length).toBeGreaterThanOrEqual(4);
    expect(screen.getAllByText(/Unavailable for this run/i).length).toBe(2);
    expect(screen.getByText(/2024-25 actual \(qtl\/ha\)/i)).toBeTruthy();
  });

  it.each([
    ['runStorageFailed', /The results could not be stored/, /536 estimates were stored/],
    ['runIncompatible', /This dataset cannot supply the model/, /no season values/],
  ] as const)('shows a failed run (%s) as a specific message', async (key, heading, detail) => {
    const stubbed = globalThis.fetch;
    globalThis.fetch = (async (input: RequestInfo | URL, init?: RequestInit) => {
      if (String(input).endsWith('/api/sandbox/runs') && init?.method === 'POST') {
        return new Response(JSON.stringify(sandbox[key].status), {
          status: 201,
          headers: { 'Content-Type': 'application/json' },
        });
      }
      return stubbed(input, init);
    }) as typeof fetch;
    try {
      mount(<SandboxPage />);
      await runFromTheWizard();
      const alert = await screen.findByRole('alert');
      expect(alert.textContent).toMatch(heading);
      expect(alert.textContent).toMatch(detail);
      expect(screen.getByRole('button', { name: /Results/i }).hasAttribute('disabled')).toBe(true);
    } finally {
      globalThis.fetch = stubbed;
    }
  });
});

describe('Exports (RFP area 8)', () => {
  it('lists recent exports with the context each file carries', async () => {
    mount(<ExportsPage />);
    expect(
      await screen.findByText(/district_price_comparison_exp-4c1f2a9b77de\.xlsx/i),
    ).toBeTruthy();
    // The Download control is a link to the generated file, not an inert button.
    const downloads = screen.getAllByRole('link', { name: /^Download$/i });
    expect(downloads.length).toBeGreaterThan(0);
    expect(downloads[0].getAttribute('href')).toMatch(/\/api\/export\/exp-[a-f0-9]+\/download$/);
  });

  it('opens an export and shows the applied context attached to it', async () => {
    mount(<ExportsPage />);
    const row = await screen.findByText(/minor_crop_yield_estimates_exp-90b3ee15c204\.json/i);
    fireEvent.click(row);

    expect(await screen.findByText(/Applied context/i)).toBeTruthy();
    // The disclosure line comes from the backend's provenance_notes, not from
    // a per-figure chip the screen invents.
    expect(screen.getByText(/^Analytical Estimates$/)).toBeTruthy();
    // A file built without a query spec says so rather than implying the
    // service derived its context.
    expect(screen.getByText(/supplied by the calling surface/i)).toBeTruthy();
  });

  it('renders filter and context values using master display names with IDs in brackets in the drawer', async () => {
    mount(<ExportsPage />);
    const row = await screen.findByText(/district_price_comparison_exp-4c1f2a9b77de\.xlsx/i);
    fireEvent.click(row);

    expect(await screen.findByText(/Applied context/i)).toBeTruthy();
    // Filter uses master display name with bracketed ID: "Crop: Arhar (CR01)"
    expect(screen.getByText(/Crop: Arhar \(CR01\)/i)).toBeTruthy();
  });
});

describe('ExportModal (RFP area 8)', () => {
  it('warns before export when rows exceed the ceiling the backend reports', async () => {
    const panel = {
      title: 'Large Trend',
      context: {
        panel_title: 'Large Trend',
        // Labels as the backend sends them in applied_context.
        filters: [
          {
            dimension: 'crop',
            values: ['CR18'],
            dimension_label: 'Crop',
            values_display: ['Potato (CR18)'],
          },
          {
            dimension: 'district',
            values: ['OD01'],
            dimension_label: 'District',
            values_display: ['Angul (OD01)'],
          },
        ],
        period: '2013-14 to 2024-25',
        row_count: 1000,
        underlying_row_count: 120000,
        source_datasets: [],
        data_origin: {},
        caveats: [],
      },
    };
    mount(
      <ExportModal
        open={true}
        onClose={() => {}}
        exportType="dashboard_panel"
        panel={panel}
      />,
    );
    // The ceiling arrives from GET /exports/limits, so the warning follows it.
    expect(await screen.findByText(/Export row ceiling exceeded/i)).toBeTruthy();
    expect(screen.getByRole('alert')).toBeTruthy();
    expect(screen.getByText(/Crop: Potato \(CR18\) · District: Angul \(OD01\)/i)).toBeTruthy();
    expect(screen.getByText(/Truncated at 100,000 of 120,000 rows/i)).toBeTruthy();
  });

  it('shows a filter without backend labels as it is, rather than guessing one', () => {
    const panel = {
      title: 'Assistant answer',
      context: {
        panel_title: 'Assistant answer',
        filters: [{ dimension: 'crop', values: ['CR18'] }],
        period: '2024-25',
        row_count: 12,
        source_datasets: [],
        data_origin: {},
        caveats: [],
      },
    };
    mount(
      <ExportModal open={true} onClose={() => {}} exportType="assistant_answer" panel={panel} />,
    );
    expect(screen.getByText('crop: CR18')).toBeTruthy();
    expect(screen.queryByText(/Potato/)).toBeNull();
  });
});

