# OISS PoC — shared project context (read this first, for every task)

Paste this file **above** any of the numbered task prompts. Each task prompt assumes it. Written so any coding
assistant can pick up the work without the original conversation.

## What is being built

A proof of concept for a TCS response to an RFP from the **Directorate of Economics & Statistics (DE&S), Odisha**.
It demonstrates one continuous statistical data journey: a file is ingested, validated, traced through storage
layers, analysed on dashboards, explained by GenAI, modelled in a guided sandbox, and exported.

The RFP scope has eight areas: (1) data ingestion and validation, (2) data storage and lineage, (3) interactive
analytics dashboard, (4) GenAI dashboard explanation, (5) conversational analytics assistant, (6) crop-yield
forecasting, (7) data science sandbox, (8) data export.

**Implementation boundary, straight from the RFP:** everything the evaluator touches must genuinely work — UI,
navigation, filters, upload, validation, charts, model-run interactions, assistant responses, exports. Everything
behind it — production databases, ETL engines, model-training infrastructure, API gateway, workflow engine, ArcGIS,
MLOps — may be represented with realistic mock data, deterministic workflows or precomputed outputs.

It is a demo. Prefer small, working and honest over general and unfinished.

## Stack

- **Backend:** Python 3.13, FastAPI, DuckDB, pandas. Runs on port **8001**.
- **Frontend:** React + TypeScript + Vite, Tailwind, Recharts.
- **External service:** a teammate's crop-yield model API (FastAPI, port **8000**), in a separate repo. Called over
  HTTP, never vendored.
- Windows development machine. Keep commands PowerShell-friendly.

## Repository

```
oiss-poc/
├── scripts/      one-off extractors and generators (already run; do not modify)
├── data/
│   ├── raw/          downloaded DE&S files, read-only
│   ├── extracted/    CSVs produced by scripts/
│   ├── synthetic/    generated price dataset
│   └── oiss.duckdb   built by `python -m app.cli build`
├── app/          FastAPI backend: db, masters, validation, ingest, api
├── tests/        pytest
└── web/          React frontend (created in task 3)
```

## The data (all already loaded into DuckDB)

| Table | Rows | Content |
|---|---|---|
| `fact_price` | 96,864 | District × crop × price type: 6,300 official annual rows (2013-14..2018-19) + 90,564 synthetic monthly rows (2013-14..2024-25) |
| `fact_crop_ayp` | 17,952 | EARAS area / yield / production, district and block grain, 2022-23..2024-25 |
| `fact_land_use` | 8,916 | Nine-fold land use, block and district grain |
| `fact_state_series` | 5,632 | State-level area / yield / production by crop and season, **1993-94 to 2024-25** |
| `dim_district` 30 · `dim_crop` 23 · `dim_block` 344 · `dim_period` 185 | | District master has 103 alias spellings; IDs are `OD01`–`OD30` |
| `dataset_version`, `lineage_edge`, `validation_finding`, `load_run` | | Governance: versions, lineage graph, findings, load history |

## Five facts about this data that shape every feature

1. **DE&S publishes no usable price statistics.** The catalogue has none; the newest published price report stops at
   2018-19. Real district prices for 2013-14..2018-19 were extracted from that PDF. Everything monthly, and
   everything after 2018-19, is **synthetic**, generated from the real data and approved by the project lead for
   demo use.
2. **Every fact row carries `data_origin`** (`official` or `synthetic`) and synthetic price rows also carry
   `annual_level_basis` (`published` / `imputed` / `projected`). This must reach the UI, the narrative, the
   assistant and every export. Synthetic figures must be visibly badged. Never present them as DE&S statistics.
3. **Paddy prices are not observed prices.** The publication substituted Minimum Support Price for paddy; those rows
   are flagged and must be labelled wherever they appear.
4. **Predictive outputs are labelled "Analytical Estimates"**, an RFP requirement. The label is a property of the
   data, not a UI decoration, and must appear in results, dashboards and exports.
5. **Some district figures are aggregated from block rows** (2022-23 paddy, which DE&S publishes only block-wise).
   Those rows carry `grain_source`, and the aggregation is a lineage edge.

## The semantic layer (built in task 2 — everything queries through it)

- A registry of **metrics** (`avg_price`, `price_yoy_pct`, `fhp_wholesale_gap`, `area`, `production`, `yield_rate`,
  `yield_yoy_pct`, `production_share_pct`, `land_use_share_pct`, …) and **dimensions** (`district`, `block`, `crop`,
  `crop_group`, `season`, `agri_year`, `month`, `price_type`, `land_use_category`, `product`, `data_origin`,
  `grain_source`).
- `POST /query` takes a **query spec** (metric, dimensions, filters, period, ordering, limit), validates it against
  the registry and compiles parameterised SQL. Nothing else writes SQL.
- Every response carries `applied_context` (filters, period, source dataset versions, data-origin mix, grain mix,
  row count) and machine-readable `caveats` (`SYNTHETIC_DATA`, `PROJECTED_LEVELS`, `MSP_SUBSTITUTED`,
  `AGGREGATED_FROM_BLOCKS`, `STRUCTURALLY_ABSENT`, `CROSS_SOURCE_MISMATCH`, `PERIOD_GAP`).
- `POST /query/records` returns the underlying fact rows behind a result cell (drill-down), with
  `dataset_version_id`, source file and cell status.
- `POST /query/narrative-facts` returns a precomputed fact bundle for a dashboard view — totals, period-on-period
  movement, leading and lagging districts, largest changes, anomalies, caveats — in pure SQL.

## Rules that hold for every task

1. **The LLM never computes numbers and never writes SQL.** It verbalises a fact bundle, or it emits a query spec
   that the backend validates and executes. Any number on screen comes from SQL.
2. **Never fabricate data.** If something is not in the sources, say so in the UI rather than filling it in.
3. **Deterministic demo.** Same inputs produce the same outputs; cache LLM responses for predefined questions so a
   slow or failed API call cannot break a live demo.
4. **Propagate provenance** — `data_origin`, `annual_level_basis`, `grain_source`, caveats, `dataset_version_id` —
   through every layer to the export.
5. **Ask before** adding a dependency, renaming a canonical table, adding a metric outside the registry, or
   inventing data.
