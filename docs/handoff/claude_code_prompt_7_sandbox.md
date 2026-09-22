# Task 7 — crop-yield sandbox: adapter + guided workspace (RFP areas 6 and 7)

Read `00_project_context.md` first. Requires tasks 2, 4 and 5.

RFP area 6 (crop-yield forecasting) is a preset scenario **inside** area 7 (the data science sandbox): the demo flow
says the crop-yield scenario runs through the guided sandbox. Build one wizard with that scenario as its default.

## 1. The external model service

A teammate owns a FastAPI service (separate repo, port **8000**) that predicts minor-crop yield. It exposes:

```
GET  /health              model status, R² (0.661)
GET  /metadata            30 districts, 3 seasons, 13 crops, area range
POST /predict             {district, season, minor_crop, area_ha}
                       -> predicted_yield_qtl_per_ha, estimated_production_qtls,
                          output_label: "Analytical Estimates", plain_language_explanation
GET  /actual-vs-predicted held-out test records with residuals and metrics
GET  /feature-importance  ranked weights + prose
```

Constraints you must design around:
- It uses its own spellings (`ANUGUL`, `KHURDA`, `BLACKGRAM`, `GREENGRAM`, `HORSEGRAM`, `NIGER`). Translate to and
  from `district_id` / `crop_id` in the adapter using the district and crop masters. **IDs cross your API boundary,
  never spellings.**
- It is **synchronous and single-record**. The sandbox needs runs and series.
- It is trained on **one year (2024-25) of data** and has **no time dimension**, so it estimates yield given area
  rather than forecasting forward. Label the UI accordingly — "analytical estimate", not "forecast to 2027".
- Its pooled metrics are dominated by differences between crops. Show metrics as reported; make no accuracy claims
  anywhere in the UI.

## 2. Adapter in your backend

Never call the model service from the browser. Implement the contract the UI consumes:

```
GET  /sandbox/use-cases                     presets; crop-yield is the default
GET  /sandbox/datasets                      {dataset_id, label, years, grain, row_count}
GET  /sandbox/datasets/{id}/columns         selectable targets and features with dtypes and roles
POST /sandbox/runs                          {dataset_id, use_case, target, features[], split, horizon} -> {run_id}
GET  /sandbox/runs/{run_id}                 {status: queued|running|completed|failed, progress, message}
GET  /sandbox/runs/{run_id}/results         metrics (pooled and per crop), predictions[], actual_vs_predicted[],
                                            feature_importance[], explanation
POST /sandbox/runs/{run_id}/versions        save a mock model version -> {version_id}
POST /sandbox/versions/{version_id}/publish publish results to the dashboard
GET  /dashboard/forecasts                   published results for the actual-vs-forecast panel
```

- **A run is a job even though the work is instant.** Store a run row, fan out `POST /predict` calls for the selected
  districts and crops, persist results, mark `completed`. Status polling reads the row. Real training can be swapped
  in later with no UI change.
- **Cache every run's results in DuckDB.** The demo must replay identically, and must survive the model service
  being down. If it is unreachable, serve the cached run and say so.
- **Validate inputs** against the model service's `/metadata` before calling; return 400 with `UNKNOWN_DISTRICT`,
  `UNKNOWN_CROP`, `UNKNOWN_SEASON`, `AREA_OUT_OF_RANGE`.
- **Publishing writes to your database and a lineage edge** (`run → version → published forecast → dashboard`), and
  every published row carries `data_origin = 'model'` plus the Analytical Estimates label.

## 3. The guided sandbox UI

A wizard, each step reversible: **Dataset → Use case → Target → Features → Train/test split → Horizon → Run →
Results → Save version → Publish**.

- **Run step** shows real progress from the status endpoint, not a fake spinner.
- **Results step**: metrics (pooled **and per crop**), an actual-vs-predicted chart with the identity line,
  feature importance as a chart plus its prose explanation, and a predictions table.
- **Every predictive figure is badged `Analytical Estimate`**, on screen and in exports.
- **Save version** stores a mock version with its parameters; **Publish** pushes results to the dashboard's
  actual-vs-forecast panel, which stops being empty at that point.
- Export works on results, via task 5.

## 4. Tests

- Adapter translates IDs both ways for all 30 districts and 13 crops.
- A run with the model service stubbed produces a completed run with stored results.
- With the service unreachable, a previously completed run still returns results and is marked as served from cache.
- Publishing makes `GET /dashboard/forecasts` return rows, and the dashboard panel renders them.
- Every prediction row carries the Analytical Estimates label from adapter through UI to export.
