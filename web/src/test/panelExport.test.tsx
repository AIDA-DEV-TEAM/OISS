/**
 * An export must describe the panel it came from.
 *
 * The dashboard used to hand the export dialog whichever applied context the
 * KPI query had last produced, so exporting the monthly price trend attached
 * the KPI's filters and row count to a file of trend rows. A file whose
 * context does not match its data is worse than a file with no context, so
 * each panel now passes the query spec that actually produced it.
 */
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { afterEach, beforeEach, describe, expect, it } from 'vitest';

import { DashboardPage } from '@/pages/DashboardPage';
import { installFetchStub } from '@/test/server';

/** Every POST the page made, in order, so a request can be attributed. */
const posted: Array<{ path: string; body: Record<string, unknown> }> = [];

function recordPosts(): void {
  const inner = globalThis.fetch;
  globalThis.fetch = (async (input: RequestInfo | URL, init?: RequestInit) => {
    const href = typeof input === 'string' ? input : input.toString();
    if (init?.method === 'POST' && init.body) {
      posted.push({
        path: new URL(href, 'http://localhost').pathname,
        body: JSON.parse(String(init.body)) as Record<string, unknown>,
      });
    }
    return inner(input, init);
  }) as typeof fetch;
}

/** Recharts needs one in jsdom; the tests never measure anything. */
class ResizeObserverMock {
  observe() {}
  unobserve() {}
  disconnect() {}
}

if (!globalThis.ResizeObserver) {
  globalThis.ResizeObserver = ResizeObserverMock as unknown as typeof ResizeObserver;
}

function mount() {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false, gcTime: 0 } },
  });
  return render(
    <QueryClientProvider client={client}>
      <MemoryRouter future={{ v7_startTransition: true, v7_relativeSplatPath: true }}>
        <DashboardPage />
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

beforeEach(() => {
  posted.length = 0;
  installFetchStub();
  recordPosts();
});

afterEach(() => {
  cleanup();
});

/** The spec a panel's own query used, taken from the recorded /query calls. */
function specFor(predicate: (body: Record<string, unknown>) => boolean) {
  return posted.find((call) => call.path === '/api/query' && predicate(call.body))?.body;
}

describe('panel-level export context', () => {
  it('sends the exporting panel’s own query spec, not the KPI query’s', async () => {
    mount();
    await screen.findByText(/Monthly Price Trend/i);
    // Wait for the panel queries so both the KPI and the trend spec are known.
    await waitFor(() => expect(posted.filter((c) => c.path === '/api/query').length).toBeGreaterThan(3));

    const buttons = screen.getAllByRole('button', { name: /^Export$/ });
    fireEvent.click(buttons[0]);

    const dialog = await screen.findByRole('dialog');
    expect(dialog.textContent).toMatch(/Monthly Price Trend/);

    fireEvent.click(
      screen.getAllByRole('button', { name: /^Export$/ }).filter((b) => dialog.contains(b))[0],
    );

    await waitFor(() => expect(posted.some((c) => c.path === '/api/export')).toBe(true));
    const request = posted.find((c) => c.path === '/api/export');
    expect(request).toBeTruthy();
    expect(request?.body.panel_title).toBe('Monthly Price Trend');

    // The trend panel groups by month; the KPI query does not group at all.
    const spec = request?.body.query_spec as { dimensions?: string[] } | null;
    expect(spec).toBeTruthy();
    expect(spec?.dimensions).toContain('month');

    // The KPI query is the ungrouped one: it names no dimensions at all.
    const kpi = specFor((body) => ((body.dimensions as string[] | undefined) ?? []).length === 0);
    expect(kpi).toBeTruthy();
    expect(spec).not.toEqual(kpi);
  });
});
