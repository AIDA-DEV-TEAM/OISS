# Task 8 — integration, hardening and the demo run-through

Read `00_project_context.md` first. All eight RFP areas are built by now. This task makes them one demo instead of
seven features, and makes that demo survive being run live in front of the client.

## 1. The six-step flow is the acceptance test

The RFP states the demonstration flow. Make it work start to finish, in one sitting, without touching a terminal:

1. **Upload and validate** — upload a representative dataset, preview its schema, review data-quality observations.
2. **Store and trace** — show the logical storage layers, dataset metadata, version and lineage to downstream outputs.
3. **Analyse and explore** — apply dashboard filters, review KPIs and trends, compare districts or commodities, drill
   down to records.
4. **Explain and converse** — generate the data-grounded narrative, ask the predefined analytical questions.
5. **Model** — run the crop-yield scenario through the guided sandbox and review the results.
6. **Export** — download a dashboard, assistant, model or grid output together with its applied context.

Write it up as `docs/DEMO_SCRIPT.md`: each step, what is clicked, what is said, what the evaluator sees, and the
fallback if something misbehaves. Include the two or three questions most likely to be asked and the honest answer to
each (where prices come from; why some data is synthetic; what the model does and does not do).

## 2. Continuity between steps

The demo must feel like one journey, not seven screens:
- The dataset uploaded in step 1 is traceable in step 2 and queried in step 3.
- Filters set on the dashboard carry into the narrative and the assistant.
- The sandbox's published results appear in the dashboard's actual-vs-forecast panel.
- Every export names the view it came from.

## 3. Hardening

- **One-command start**: a script that launches backend (8001), frontend and, if present, the model service (8000),
  and a health page showing all three plus the database build time and row counts.
- **Seeded demo state**: a `python -m app.cli demo-seed` that loads the database, warms the LLM cache, and executes
  one sandbox run so the dashboard has published forecasts before anyone clicks.
- **Every external dependency has a fallback**: LLM → cache → deterministic template; model service → cached run;
  browser offline → nothing that needs the internet is on screen at all.
- **Error states everywhere**: no white screens, no raw stack traces, no infinite spinners. A failed call shows what
  failed and what still works.
- **Performance**: any dashboard interaction under ~1 s; narrative and assistant under ~5 s with a visible progress
  state. Measure and record the numbers.
- **Determinism check**: run the full flow twice from a fresh seed and diff the visible figures. They must match.

## 4. Presentation details that get noticed

- Units and labels on every axis and KPI; no unexplained abbreviations.
- Legible at 1366×768 on a projector.
- Consistent terminology with DE&S usage: agricultural year, season names (Autumn / Winter / Summer), quintals,
  hectares, district names in the master's display spelling.
- Provenance badges present on every screen where synthetic or model-derived figures appear.
- No TCS-internal jargon, no placeholder text, no "TODO" visible anywhere.

## 5. Documentation to leave behind

- `README.md`: what it is, how to run it, what is real and what is represented.
- `docs/DATA_SOURCES.md`: every dataset, its URL, download date, checksum, licence/access status, and — for the
  synthetic price dataset — what it is modelled on, the generator version and seed, and the fact that its use was
  approved for the PoC.
- `docs/ARCHITECTURE.md`: the layers, the semantic layer, where the LLM sits and what it is prevented from doing.
- `docs/SCOPE_COVERAGE.md`: a table mapping each of the eight RFP scope areas to what was built, and stating plainly
  what is represented rather than production-grade (ETL engine, workflow engine, ArcGIS, MLOps, API gateway).

## 6. Final checks

- The six-step flow passes twice in a row from a fresh seed.
- Every screen shows provenance where it applies; no synthetic or model figure is unbadged.
- Exports open correctly in Excel, a PDF reader and a text editor, and each carries its context.
- No number on screen is produced by an LLM.
- The test suite passes; `npm run build` is clean.
