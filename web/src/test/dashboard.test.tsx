import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { afterEach, beforeAll, beforeEach, describe, expect, it } from 'vitest';

import { DashboardPage } from '@/pages/DashboardPage';
import { installFetchStub } from '@/test/server';

function mount(initialEntries = ['/dashboard']) {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false, gcTime: 0 } },
  });
  return render(
    <QueryClientProvider client={client}>
      <MemoryRouter
        initialEntries={initialEntries}
        future={{ v7_startTransition: true, v7_relativeSplatPath: true }}
      >
        <DashboardPage />
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

class ResizeObserverMock {
  observe() {}
  unobserve() {}
  disconnect() {}
}

if (!globalThis.ResizeObserver) {
  globalThis.ResizeObserver = ResizeObserverMock as any;
}

beforeAll(() => {
  installFetchStub();
});

beforeEach(() => {
  installFetchStub();
});

afterEach(() => {
  cleanup();
});

describe('Dashboard — Interactive Analytics (RFP Area 3)', () => {
  it('renders the dashboard frame with header, sticky filter bar, and applied context strip', async () => {
    mount(['/dashboard']);
    expect(await screen.findByText('Interactive Analytics Dashboard')).toBeTruthy();
    expect(screen.getByRole('tab', { name: /Price Statistics/i })).toBeTruthy();
    expect(screen.getByRole('tab', { name: /Agriculture \/ EARAS/i })).toBeTruthy();

    // Applied context strip
    expect(await screen.findByText('Active dataset versions')).toBeTruthy();
    expect(await screen.findByText(/Rows shown/i)).toBeTruthy();
  });

  it('renders Price Statistics (Primary view) KPIs, charts, and MSP caveat banner', async () => {
    mount(['/dashboard?view=price']);

    // MSP substitution caveat banner for Paddy
    expect(
      await screen.findByText(/Paddy Price Methodology Caveat: Minimum Support Price/i),
    ).toBeTruthy();

    // KPI Cards
    expect((await screen.findAllByText(/Average Price/i)).length).toBeGreaterThan(0);
    expect(screen.getByText(/Year-on-Year Movement/i)).toBeTruthy();
    expect(screen.getByText(/Wholesale Premium over Farm Harvest/i)).toBeTruthy();

    // Chart panels
    expect(screen.getByText(/Monthly Price Trend/i)).toBeTruthy();
    expect(screen.getByText(/Average Price by District/i)).toBeTruthy();
    expect(screen.getByText(/Price Comparison Across Commodities/i)).toBeTruthy();
    expect(screen.getByText(/Farm Harvest vs Wholesale Price Spread/i)).toBeTruthy();
  });

  it('asserts the known figure end-to-end: paddy production 2023-24 renders as 174.83 lakh MT', async () => {
    mount(['/dashboard?view=agriculture&from=2023-24&to=2023-24&crop=CR17']);

    // The KPI card label
    expect(await screen.findByText('Total Production')).toBeTruthy();

    // The formatted figure: 174,828,800 quintals / 1e6 = 174.83 lakh MT
    await waitFor(() => {
      const figure = screen.getByText('174.83');
      expect(figure).toBeTruthy();
      expect(screen.getAllByText('lakh MT').length).toBeGreaterThan(0);
    });

    // Area and Yield Rate KPIs
    expect(screen.getByText('Total Area')).toBeTruthy();
    expect(screen.getByText('State Yield Rate')).toBeTruthy();
  });

  it('renders Agriculture / EARAS view with long-run 32-year state series, district yield, and land use', async () => {
    mount(['/dashboard?view=agriculture']);

    // 32-year state series panel
    expect(await screen.findByText(/Long-Run State Historical Series/i)).toBeTruthy();
    expect(screen.getByText(/32 Years of Genuine DE&S Official Data/i)).toBeTruthy();

    // District yield and production panel
    expect(screen.getByText(/District Yield & Production Comparison/i)).toBeTruthy();

    // 9-fold land use composition panel
    expect(screen.getByText(/Land-Use Composition/i)).toBeTruthy();

    // Forecast empty state with analytical estimate hedging
    expect(await screen.findByText(/Actual against model estimate/i)).toBeTruthy();
    // Published model output discloses itself once, in the panel header.
    expect(await screen.findByText(/^Analytical Estimates$/)).toBeTruthy();
  });

  it('switches between Price and Agriculture views via the view tab buttons', async () => {
    mount(['/dashboard?view=price']);

    expect(await screen.findByText(/Monthly Price Trend/i)).toBeTruthy();

    // Click on Agriculture / EARAS tab
    const agTab = screen.getByRole('tab', { name: /Agriculture \/ EARAS/i });
    fireEvent.click(agTab);

    // Agriculture content appears
    expect(await screen.findByText('Total Area')).toBeTruthy();
    expect(screen.getByText(/Long-Run State Historical Series/i)).toBeTruthy();
  });

  it('opens drill-down drawer showing fact records with dataset versions when requested', async () => {
    mount(['/dashboard?view=price']);

    // Find a record row in the Price Statistics grid table
    const cells = await screen.findAllByText('Bargarh');
    const tableCell = cells.find((el) => el.closest('tr')) ?? cells[0];
    fireEvent.click(tableCell);

    // Drawer opens with fact records
    expect(await screen.findByText(/Supporting fact rows|Record details/i)).toBeTruthy();
    expect(await screen.findByText(/dist_paddy_AYP_2023-24\.csv/i)).toBeTruthy();
    expect(screen.getByText(/earas_2023_24_district_paddy@5e8bdea5ea67/i)).toBeTruthy();
  });

  it('opens the export dialog showing the context that will travel with the file', async () => {
    mount(['/dashboard?view=price']);

    await screen.findByText(/Monthly Price Trend/i);

    const exportButtons = await screen.findAllByRole('button', { name: /^Export$/i });
    expect(exportButtons.length).toBeGreaterThan(0);
    fireEvent.click(exportButtons[0]);

    const dialog = await screen.findByRole('dialog');
    expect(dialog).toBeTruthy();
    // Task 5's rule: the file carries its applied context, previewed here.
    expect(await screen.findByText(/Context that travels with the file/i)).toBeTruthy();
    expect(screen.getByLabelText(/Excel/i)).toBeTruthy();
    expect(screen.getByLabelText(/Chart image/i)).toBeTruthy();
  });

  it('offers one crop at a time, and only the crops the view holds data for', async () => {
    mount(['/dashboard?view=agriculture']);

    const picker = (await screen.findByLabelText(/^Crop:/i)) as HTMLSelectElement;
    await waitFor(() => expect(picker.disabled).toBe(false));
    // A single-choice list, built from the crops with area on record.
    expect(picker.multiple).toBe(false);
    expect(Array.from(picker.options).map((o) => o.textContent)).toEqual([
      'Mustard',
      'Paddy',
      'Potato',
    ]);

    fireEvent.change(picker, { target: { value: 'CR18' } });
    expect(picker.value).toBe('CR18');
  });

  it('asks for seasons only where seasons exist, and for one price series at a time', async () => {
    mount(['/dashboard?view=price']);
    expect(await screen.findByLabelText(/^Series:/i)).toBeTruthy();
    expect(screen.queryByLabelText(/^Season:/i)).toBeNull();

    fireEvent.click(screen.getByRole('tab', { name: /Agriculture \/ EARAS/i }));
    const season = (await screen.findByLabelText(/^Season:/i)) as HTMLSelectElement;
    // The crop reports' Total row repeats the seasons' sum and is not offered.
    expect(Array.from(season.options).map((o) => o.value)).toEqual([
      '',
      'Autumn',
      'Winter',
      'Summer',
    ]);
    expect(screen.queryByLabelText(/^Series:/i)).toBeNull();
  });

  it('describes the view from its SQL facts and says what wrote the description', async () => {
    mount(['/dashboard?view=agriculture']);

    expect(await screen.findByText(/What this view shows/i)).toBeTruthy();
    expect(await screen.findByText(/442,545,882 qtl, across 30 districts with data/i)).toBeTruthy();
    expect(screen.getByText(/Stated from the figures by a template/i)).toBeTruthy();
    expect(screen.getByText(/Facts used/i)).toBeTruthy();
  });
});
