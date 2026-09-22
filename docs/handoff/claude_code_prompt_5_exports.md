# Task 5 — export service (RFP area 8)

Read `00_project_context.md` first. Backend on 8001; dashboard from task 4 exists.

The RFP requires exports from dashboards, assistant results, model outputs and data grids in **CSV, Excel, PDF, JSON
and chart-image** formats, and says at least one real downloadable export must be produced from the PoC dataset.
Build this now, before the GenAI and sandbox work, so every later module plugs into one export path instead of
growing its own.

## 1. The rule that makes exports credible

**An export carries its applied context.** Not just rows — the filters, period, source dataset versions,
data-origin mix, grain mix and caveats that produced them. A file that leaves the system without that context is a
file nobody can defend six months later.

## 2. Backend

```
POST /export        {export_type, query_spec | payload_ref, format, options} -> {export_id}
GET  /export/{id}                    -> status, then the file
GET  /exports                        -> recent exports with their context (for an Exports screen)
```

- `export_type`: `dashboard_panel` | `records_grid` | `assistant_answer` | `model_output` | `narrative`.
- `format`: `csv` | `xlsx` | `pdf` | `json` | `png` (chart image).
- **Every export records a row in `dataset_version` (or an `export` table) and a `lineage_edge`** from the analytics
  tables to the export, so the lineage graph shows exports as leaf nodes.

Format specifics:
- **CSV**: data rows plus a commented header block with the context, or a companion `_context.csv`. State which.
- **Excel**: sheet 1 data, sheet 2 **Context** (filters, period, datasets, versions, caveats, generated-at), sheet 3
  **Caveats** when there are any. Column headers carry units.
- **JSON**: `{data: [...], applied_context: {...}, caveats: [...]}` — the query response, verbatim.
- **PDF**: a titled report — heading, the filter summary, the table or chart, caveats as footnotes, and a footer with
  dataset versions and generation time. Use ReportLab or WeasyPrint.
- **PNG**: the chart image. Render server-side (matplotlib) from the same query result, not by screenshotting the
  browser, so the image is reproducible.

Provenance rules, non-negotiable:
- Rows keep `data_origin`; any export containing synthetic rows says so **in the file**, not only on screen.
- Model outputs keep the **Analytical Estimates** label.
- Paddy price exports carry the MSP caveat.
- District figures aggregated from blocks keep `grain_source`.

## 3. Frontend

- Export control on every dashboard panel, the records grid, assistant answers and model results: pick a format,
  show progress, download.
- An **Exports screen** listing recent exports with their context, so the evaluator can see what was produced and
  re-download it.

## 4. Tests

- One export per format from a real query; open each and assert the context is present.
- An export of a synthetic-price selection contains a synthetic declaration in-file.
- An export row count equals the query's `row_count`.
- The lineage graph contains the export node after an export runs.
- Excel numbers are typed as numbers, not text, and dates are dates.
