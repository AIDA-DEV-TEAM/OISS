# Mock inventory

Every mocked surface in `web/`, what it feeds, and the endpoint that replaces it.

Mocks exist only where the backend does not yet have the endpoint — tasks 5, 6 and 7. Everything
with a live endpoint calls it for real; no screen mixes a real call with a mocked one for the same
figure.

## How the switch works

- `web/src/mocks/config.ts` exports `USE_MOCKS` (currently `true`) and `mockDelay`, which resolves
  on a timer so loading states are exercised rather than skipped.
- `web/src/api/contracts.ts` holds the response types for the endpoints tasks 5–7 will build,
  copied from the contracts in `docs/handoff/claude_code_prompt_5_exports.md`, `_6_genai.md` and
  `_7_sandbox.md`. Mocks are typed against these, so a shape mismatch is a compile error.
- Each feature has one adapter in `web/src/api/`. The adapter is the only place that consults
  `USE_MOCKS`. **Making a feature real means editing its adapter — one file, one branch.** No
  component imports a mock, and no component changes.

```
component  →  src/api/<feature>.ts (adapter)  →  USE_MOCKS ? src/mocks/<feature>.ts : api.<call>
```

Mocked data renders exactly like real data: no sample-data banners, no different styling. Values
are realistic for Odisha — districts and crops from `dim_district` and `dim_crop`, quintals and
hectares, magnitudes that match what EARAS publishes.

## Files

| Mock file | Adapter | Screen / component | Replace with |
|---|---|---|---|
| `src/mocks/forecasts.ts` | `src/api/forecasts.ts` | Dashboard → `ActualVsForecastPanel` | `GET /dashboard/forecasts` (task 7) |
| `src/mocks/narrative.ts` | `src/api/narrative.ts` | Dashboard → `NarrativePanel`, both views | `POST /narrative/dashboard` (task 6) |
| `src/mocks/assistant.ts` | `src/api/assistant.ts` | Assistant → question chips, `AnswerCard` | `GET /assistant/questions`, `POST /assistant/ask` (task 6) |
| `src/mocks/sandbox.ts` | `src/api/sandbox.ts` | Sandbox → every wizard step | `GET /sandbox/use-cases`, `/sandbox/datasets`, `/sandbox/datasets/{id}/columns`, `POST /sandbox/runs`, `GET /sandbox/runs/{id}`, `GET /sandbox/runs/{id}/results`, `POST /sandbox/runs/{id}/versions`, `POST /sandbox/versions/{id}/publish` (task 7) |
| `src/mocks/exports.ts` | `src/api/exports.ts` | `ExportModal` (create), Exports screen (list) | `POST /export`, `GET /export/{id}`, `GET /exports` (task 5) |
| `src/mocks/config.ts` | — | The `USE_MOCKS` flag and `mockDelay` | Delete once every feature is real |

## What each mock contains

**`forecasts.ts`** — 18 published minor-crop yield estimates for 2024-25 across 8 districts and 6
crops, in qtl/ha. Four rows carry `actual_yield: null` so the panel demonstrates that a null is a
gap, never a zero. Every row carries `data_origin: { model: 1 }` and the Analytical Estimates label.

**`narrative.ts`** — one grounded narrative per dashboard view. Every number in the prose also
appears in `facts_used`; that is the invariant task 6 enforces by post-validating model output
against the fact bundle, and holding to it here means the panel behaves identically once wired.
The price narrative carries the MSP and synthetic caveats; the agriculture one carries the
block-aggregation caveat.

**`assistant.ts`** — six predefined questions covering what prompt 6 asks a demo to show: a district
comparison, a trend over time, a leading/lagging question, a farm-harvest versus wholesale
question, one that must surface the MSP caveat, and **one the assistant declines** because block
grain does not exist for prices and official price data ends at 2018-19.

**`sandbox.ts`** — use cases (crop-yield is the default preset), three datasets, seven selectable
columns, a six-step run lifecycle the page polls through, and a results bundle: pooled metrics
(R² 0.661, matching the model service), per-crop metrics for 8 crops, 20 actual-vs-predicted
records, 4 ranked features with prose, and 14 prediction rows.

**`exports.ts`** — six completed exports across all five formats, each carrying a full
`ExportContext`: filters, period, row count, dataset versions, origin mix, grain mix and caveats.
`mockCreateExport` mirrors `POST /export` followed by the job completing.

## Screens by how real they are

| Screen | Status | Notes |
|---|---|---|
| Ingest | **Fully real** | `/datasets`, `/ingest/upload`, `/datasets/{id}/validation`, `/validation/summary` |
| Storage & lineage | **Fully real** | `/datasets`, `/datasets/{id}/layers`, `/lineage/{id}` |
| Dashboard | **Partly mocked** | All KPIs, charts, tables and drill-downs use real `POST /query` and `/query/records`. Two panels are mocked: the narrative and actual-vs-forecast. The export control is mocked. |
| Assistant | **Entirely mocked** | No assistant endpoint exists. Answers, charts and records are cached fixtures. |
| Sandbox | **Entirely mocked** | No `/sandbox/*` endpoints exist. The external model service on port 8000 is never called from the browser by design — the backend adapter in task 7 will own that. |
| Exports | **Entirely mocked** | No export endpoints exist. The Download button is inert. |

## Known gaps behind the mocks

- **No file is actually produced.** The export dialog and the Exports screen render a completed job
  and a Download button, but nothing is generated or downloadable until task 5 builds the service.
- **The assistant does not call a model.** Answers are fixtures keyed by question id. The real path
  (model emits a query spec → backend validates against the registry → executes → model verbalises
  the rows, post-validated) is task 6.
- **The sandbox does not call the model service.** Metrics mirror what it reports but are static.
- **Publishing does not persist.** Completing the sandbox wizard sets local state; it does not write
  a version, a lineage edge, or rows the dashboard reads across a reload.
