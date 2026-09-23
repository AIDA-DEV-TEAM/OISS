# Mock inventory

**Nothing in `web/` is mocked any more.** `web/src/mocks/` is gone, along with the `USE_MOCKS`
flag and the hand-written contracts in `src/api/contracts.ts`. Every screen calls a real endpoint,
and every response type is generated from the backend's OpenAPI document into `src/api/types.ts`.

What remains depends on something outside this repository — a language-model key, or the crop-yield
model service — and each such dependency is described below, with what the screen does without it.

**Exports are not mocked.** Task 5 built `POST /export`, `GET /exports`, `GET /exports/limits`,
`GET /export/{id}` and `GET /export/{id}/download`, and `src/api/exports.ts` calls them. Files are
produced server-side in all five formats and are really downloadable. The row ceiling the export
dialog warns about is read from `GET /exports/limits`, not kept in the UI.

**The sandbox and forecasts are not mocked.** Task 7 built the `/sandbox/*` adapter and
`GET /dashboard/forecasts`; `src/api/sandbox.ts` and `src/api/forecasts.ts` call them, typed from
the generated `src/api/types.ts`. `src/mocks/sandbox.ts` and `src/mocks/forecasts.ts` are gone.
The sandbox is real, but it depends on the external model service — see below.

**The assistant is not mocked.** Task 6 built `GET /assistant/questions` and `POST /assistant/ask`;
`src/api/assistant.ts` calls them and `src/mocks/assistant.ts` is gone. The model (Gemini, behind
`app/llm/provider.py`) only ever returns a query spec or a refusal; the backend validates the spec
against the registry, runs it through the semantic layer and checks every number in the model's
paragraph against the result rows. What is and is not live:

- **Starter questions answer from a shipped cache**, `data/llm_cache/`, keyed by a hash of the exact
  model input. No model key was available when it was recorded, so its responses were written by
  hand against the real result rows by `python -m app.cli seed-assistant` and recorded as model
  `fixture`. They pass the same spec validation and number check as a live response, and the answer
  screen's "How this was answered" section names `fixture` as the reader, so they are never passed
  off as model output. The figures in them come from SQL either way.
- **Free-text questions need `LLM_API_KEY`** (see `.env.example`). With no key, or with the provider
  unreachable, a question not asked before returns status `unavailable` and says so; it is never
  guessed at. With a key, a new question goes to the model once and its responses join the cache.
- **The cache is read first.** A question asked before answers identically, byte for byte, and is
  marked "Served from cache". The keys include the catalogue sent to the model (metrics, dimension
  values, coverage years), so changing the registry, the prompts or the loaded data changes them;
  re-run `seed-assistant` afterwards. Published sandbox estimates are left out of the catalogue so a
  publish does not invalidate the cache.
- **Every call is logged** to `analytics.llm_call` (prompt, response, cache flag, outcome, latency).

**The dashboard narrative is not mocked.** `POST /narrative/dashboard` takes the view's own query
spec, computes its facts in SQL (`/query/narrative-facts`: totals, the latest movement, leading and
lagging districts, the largest changes) and has the model describe them. Every number in the
paragraph is checked against those facts; one that is not gets a single retry, then the paragraph
is rendered from a template over the same facts. With no model key, and nothing cached for that
exact view, the template is what shows, and the panel says so ("Stated from the figures by a
template"). No narrative cache is shipped: every view's facts differ, and hand-writing prose to seed
it would be passing off authored text as model output.

## Screens by how real they are

| Screen | Status | Notes |
|---|---|---|
| Ingest | **Fully real** | `/datasets`, `/ingest/upload`, `/datasets/{id}/validation`, `/validation/summary` |
| Storage & lineage | **Fully real** | `/datasets`, `/datasets/{id}/layers`, `/lineage/{id}` |
| Dashboard | **Fully real** | KPIs, charts, tables and drill-downs use `POST /query` and `/query/records`; the crop list is itself a query, so it offers only crops the view holds. `ActualVsForecastPanel` uses `GET /dashboard/forecasts` and stays empty until a sandbox version is published. "What this view shows" uses `POST /narrative/dashboard`: model prose with a key, a labelled template without one. Every panel's export control is real. |
| Assistant | **Real; free text needs a model key** | `GET /assistant/questions`, `POST /assistant/ask`. Starter questions answer from the shipped cache with no key; free text goes to the model when `LLM_API_KEY` is set and is otherwise reported as unavailable. Answers, charts, filters, periods, records and caveats come from the semantic layer. Exporting an answer re-runs its validated spec, so the file's context is derived. |
| Sandbox | **Real; needs the model service** | The model is pre-trained, so the wizard offers only real choices: Dataset, then a read-only use case and model configuration, then Run. The configuration is what the service states, each field sourced: features from the `POST /predict` request schema in `/openapi.json`, model name and target from `/health`, input domains from `/metadata`; model version and training period read "not stated by the model service". Datasets and their row counts come from the database; each is checked against the request fields and the input domains, incompatible ones are disabled with the missing fields named, and out-of-domain combinations are counted by reason and never sent. With the service unreachable, a run replays an earlier live run of the same dataset (and the same configuration hash, when the configuration could be read) and says so; with none it **fails**. Failures carry a typed `error_code`. If every estimate arrives but the evaluation does not, the run keeps its estimates as `completed_with_warnings`. Estimates are shown as "Model estimate vs published <year> actual". It never supplies numbers of its own. |
| Exports | **Fully real** | `GET /exports`, `GET /export/{id}/download`. Files exist on disk under `data/exports/` and each is recorded in `analytics.export` with a lineage edge. |

## Known gaps

- **Three surfaces export by payload, not by spec.** Both narrative panels have no query spec for
  the export service to re-run, nor does the farm-harvest versus wholesale panel, which is built
  from two queries. They send their rows and context with the request, and those files state
  `Context: supplied by the calling surface` rather than `derived`.
- **`ActualVsForecastPanel` exports without its rows.** It reads `GET /dashboard/forecasts`, which
  is not a query spec, and its export sends no payload rows, so the file carries context only.
- **The sandbox's metrics are computed, not reported.** Pooled and per-crop R², RMSE and MAE are
  computed in DuckDB from the held-out records `/actual-vs-predicted` returns (all 111, at the
  service's maximum `limit` of 200). That response also carries the service's own
  `evaluation_metrics` (test R² 0.661); the sandbox does not display them.
- **A retrain the service does not announce is invisible.** The replay key hashes the `/predict`
  request schema, the `/health` model fields and the full `/metadata`, but the service states no
  model version or training period, so a retrain that changes none of those looks like the same
  model. The model service needs to add `model_version` and `training_period` to `/health` or
  `/metadata`; the sandbox reads them when present.
- **The starter answers were not written by a model.** See the assistant section above: they are
  hand-written responses recorded as `fixture`, checked like live ones, until someone with a key
  re-records them.
- **The number check reads digits, not words.** "Three districts" is not checked; a figure written
  in digits must be a value from the result (rounding allowed) or it fails.
- **Price figures read one series at a time.** Official (annual, 2013-14 to 2018-19) and synthetic
  (monthly, 2013-14 to 2024-25) are chosen with the Series control and never averaged together.
- **There is no land-use area metric.** The land-use panel shows shares only; an area column that
  used to sit beside them always read 0.0, because the query behind it was rejected by the registry.
