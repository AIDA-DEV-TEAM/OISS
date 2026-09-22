/**
 * The single switch behind every mocked feature.
 *
 * Screens whose backend endpoints exist (query, records, narrative-facts,
 * semantic, ingest, datasets, lineage) never consult this flag — they call the
 * API directly. It governs only the surfaces tasks 5, 6 and 7 have not built
 * yet: exports, GenAI narrative and assistant, and the sandbox.
 *
 * Each feature has one adapter in src/api/. Turning a feature real means
 * pointing its adapter at the endpoint; nothing in a component changes.
 */
export const USE_MOCKS = true;

/** Mock calls resolve on a timer so loading states are exercised, not skipped. */
export function mockDelay<T>(value: T, ms = 320): Promise<T> {
  return new Promise((resolve) => {
    setTimeout(() => resolve(value), ms);
  });
}
