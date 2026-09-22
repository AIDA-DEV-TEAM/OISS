# Task for Claude Code — OISS PoC data layer (schema + loader + validation)

You are building the data foundation of a proof of concept for an RFP response to the Directorate of
Economics & Statistics (DE&S), Odisha. Everything downstream — dashboard, GenAI narrative, conversational
assistant, crop-yield sandbox, exports — reads from what you build here. Nothing else is blocked on anything else,
so this is the critical path. Work fast and keep it small; this is a demo, not a production platform.

Stack: **Python 3.13, FastAPI, DuckDB, pandas**. Frontend is React, built separately — do not build UI.

## 0. Non-negotiables

1. **`data_origin` on every fact row**: `official` (published by DE&S) or `synthetic` (generated for the demo).
   It must survive every join and aggregate, because the UI has to badge synthetic figures. Never default it silently.
2. **Never mutate anything under `data/raw/`.**
3. **Deterministic**: same inputs → same database. No timestamps in data (only in load-run rows), no random ordering.
4. **One code path**: the validation used when a user uploads a file at demo time is the same code that loads the
   bundled datasets. No second implementation.
5. **Fail loudly on unknown district or crop names.** Do not fuzzy match at run time. An unmapped name is a validation
   finding, not something to guess.

## 1. Repo layout (already exists)

```
oiss-poc/
├── scripts/                 extractors + generators, already written and run (do not modify)
├── data/
│   ├── raw/                 downloaded DE&S files, read-only
│   │   ├── price/           price-statistics-odisha-2020.pdf
│   │   ├── reference/       OES_2026.xlsx, DAG_2026.xlsx
│   │   └── earas/2022-23|2023-24|2024-25/   .dta / .csv microdata + Technical Report PDFs
│   ├── extracted/           outputs of scripts/ (see §2)
│   └── synthetic/           synthetic_monthly_prices.csv + audit files
└── app/                     ← YOU CREATE THIS
```

## 2. Input files and their exact columns

All under `data/extracted/` unless noted. Column names differ between years — that is real schema drift from the
publisher, and handling it is part of the demo story. Map per-source into the canonical schema; do not rename source files.

| File | Grain | Columns |
|---|---|---|
| `price_statistics_odisha_2020_raw_long.csv` | district × commodity × price type × agri year (2013-14..2018-19) | `table_no, pdf_page, price_type, commodity, sl_no, district_as_published, year, raw_value, price_rs_per_quintal, cell_status` |
| `../synthetic/synthetic_monthly_prices.csv` | district × commodity × price type × month (2013-14..2024-25) | `agri_year, month_start, calendar_year, month, district_id, district, price_type, commodity, price_rs_per_quintal, unit, data_origin, annual_level_basis, annual_level_rs_per_quintal, generator_version, generator_seed` |
| `earas_2024_25_district_crop_ayp_raw.csv` | district × season × crop × measure (2024-25) | `reference_year, source_report, pdf_page, table_no, crop_table, product, sl_no, district_as_published, is_state_total, season, measure, unit, raw_value, value, cell_status` |
| `earas_2024_25_district_land_use_raw.csv` | district × land-use category (2024-25) | `reference_year, source_report, pdf_page, table_no, sl_no, district_as_published, is_state_total, land_use_category, measure, unit, raw_value, value, cell_status` |
| `earas_state_series_latest.csv` | state × crop × season × measure × year (1993-94..2024-25) | `reference_year, crop, product, season, measure, unit, raw_value, value, cell_status, source_report, report_year, table_no, pdf_page, reports_containing_value` |
| `district_master.csv` | 30 districts | `district_id, display_name, lgd_name, lgd_code, census_2011_code, headquarters, state_name, state_lgd_code, code_verification` |
| `district_aliases.csv` | 103 aliases | `name_as_published, normalised_key, district_id, display_name, label_type, n_sources, occurrences, sources` |

EARAS microdata under `data/raw/earas/` (read the `.csv` for 2023-24, the `.dta` via `pandas.read_stata` for 2022-23):

| File | Rows | Columns |
|---|---|---|
| `2022-23/blockwise_LUS_202223.dta` | 4128 | `Year, District, Block, Code, Block_Urban_Dist_State_Total, Land_Use_Category, Area_Hectare` |
| `2022-23/blockwise_paddy_AYP_2022-23.dta` | 1032 | `Year, District, Block, Block_Urban_Dist_total, Season, Crop, Area_ha, YieldRate_qtl_per_ha, Production_qtl` |
| `2022-23/distwise_minorcrops_AYP2022-23.dta` | 837 | `Year, District, Season, Crop, Area_hectares, Yield_Rate_qtl_ha, Prodn_quintals` |
| `2023-24/blockwise_LUS_2023_24.csv` | 4128 | `Year, District, Block, Code, Block_Urban, Land Use Category, Area in Ha` |
| `2023-24/blockwise_paddy_AYP_2023_24.csv` | 1032 | `Year, District, Block, Block_Urban, Season, Crop, Area_ha, Yield_qtl_per_ha, Production_qtls` |
| `2023-24/dist_paddy_AYP_2023-24.csv` | 180 | `Year, District, Season , Crop_Paddy_Rice, Area_000ha, Yield_rate_qtl_ha, Production_000MT` |
| `2023-24/distwise_minor_crop_AYP_2023-24.csv` | 1170 | `Year, District, Season, Minor_Crop , Area_ha, Yield_rate_qtl_per_ha, Production_qtls` |

Known traps, all real:
- **BOM**: two 2023-24 CSVs start with a UTF-8 BOM → read with `encoding='utf-8-sig'`.
- **Trailing spaces in headers**: `Season `, `Minor_Crop ` → strip header whitespace on read.
- **Year format**: `2022_23` in the 2022-23 files, `2023-24` elsewhere → normalise to `YYYY-YY`.
- **State totals mixed into district rows**: `ORISSA  STATE` (two spaces) in 2022-23 minor crops; `STATE` in the
  2024-25 extracts (`is_state_total = 1`). Never let these into district-level aggregates.
- **Urban rows**: the block files carry one `Urban` row per district alongside blocks (`Block_Urban` column).
- **"Not grown"**: 2022-23 uses `0`, 2023-24 uses blank. Keep both as NULL with a `value_status` of `not_reported`.
- **`S` marker**: in the 2024-25 extracts, `cell_status = 'below_half_unit'` means less than 0.5 units, not zero.
- **Block names do not join across files**: 70 of 314 district-block pairs are spelled differently between the
  land-use and paddy files (`Athamalik`/`Athamallik`, `Cheendipada`/`Chhendipada`), and only the land-use file has
  the block `Code` (1..314). Block names also repeat across districts (`Nuagaon` in 3-4). **Key blocks on
  (district_id, normalised block name); never on block name alone.** Build `dim_block` from the land-use file's
  Code, and record unmatched paddy blocks as a validation finding rather than dropping them.

## 3. Build a crop master (mirroring the district master)

Same pattern as `district_master.csv` / `district_aliases.csv`: a curated table, deterministic lookup, loud failure on
unknown names. Vocabularies actually present:

- 2022-23 EARAS: `BLACKGRAM, GREENGRAM, GROUNDNUT, HORSEGRAM, JUTE, MAIZE, MUSTARD, NIGER, POTATO, RAGI, SUGARCANE, TIL, WHEAT`
- 2023-24 EARAS: `Biri, Groundnut, Jute, Kulthi, Maize, Mung, Mustard, Nizer, Potato, Ragi, Sugarcane, Til, Wheat`
- 2024-25 report: same as 2023-24 plus `Paddy`, and the typo **`Grountnut`** (as printed)
- Price data: `Arhar, Bajra, Biri, Castor, Cotton, Gram, Groundnut, Jowar, Jute, Kulthi, Linseed, Maize, Mung, Mustard, Onion, Paddy, Potato, Ragi, Sugarcane, Sunflower, Til, Wheat`
- The teammate's yield API: `BLACKGRAM, GREENGRAM, GROUNDNUT, HORSEGRAM, JUTE, MAIZE, MUSTARD, NIGER, POTATO, RAGI, SUGARCANE, TIL, WHEAT`

Equivalences: Biri = Blackgram, Mung = Greengram, Kulthi = Horsegram, Nizer = Niger, Grountnut = Groundnut.
Give each crop a `crop_id`, a display name, a group (cereal / pulse / oilseed / fibre / tuber / sugar), and an
`in_earas` / `in_price` flag. Write it as `app/masters/crop_master.py` plus a generated `data/extracted/crop_master.csv`.

## 4. Canonical schema (DuckDB, file at `data/oiss.duckdb`)

Dimensions
- `dim_district(district_id PK, display_name, lgd_name, lgd_code, census_2011_code, headquarters)`
- `dim_block(block_id PK, district_id FK, block_code, display_name, is_urban)`
- `dim_crop(crop_id PK, display_name, crop_group, in_earas, in_price)`
- `dim_period(period_id PK, agri_year, season, month_start NULL, period_type: 'year'|'season'|'month')`

Facts (every fact carries `dataset_version_id`, `data_origin`, `value_status`)
- `fact_price(period_id, district_id, crop_id, price_type ENUM('farm_harvest','wholesale'), price_rs_per_quintal, ...)`
  — annual official rows from the price extract **and** monthly synthetic rows, in one table, separated by
  `data_origin` and `period_type`. Keep `annual_level_basis` for synthetic rows.
- `fact_crop_ayp(period_id, district_id, block_id NULL, crop_id, product ENUM('paddy','rice','minor'), measure
  ENUM('area','yield_rate','production'), value, unit, ...)` — all three EARAS years, block rows where available.
- `fact_land_use(period_id, district_id, block_id NULL, land_use_category, measure, value, unit, ...)`
- `fact_state_series(period_id, crop_id, product, season, measure, value, unit, ...)` — 1993-94..2024-25.

Governance tables (these are demo features, not bookkeeping — the RFP asks for lineage and versioning)
- `dataset_version(dataset_version_id PK, dataset_name, source_file, source_type, sha256, row_count, layer, loaded_at, generator_version NULL)`
- `lineage_edge(from_node, to_node, edge_type, dataset_version_id)` — source file → raw table → staging → analytics → export
- `validation_finding(run_id, dataset_version_id, rule_code, severity ENUM('error','warning','info'), row_ref, column_name, message, observed_value)`
- `load_run(run_id PK, started_at, finished_at, status, summary_json)`

Layers are schemas in one DuckDB file: `raw` (as-published, all text), `quarantine` (rows failing an error rule),
`staging` (typed + canonical IDs), `analytics` (the facts above + views).

## 5. Validation rules (implement as named, reusable rules)

Each returns findings with `rule_code` and severity; errors quarantine a row, warnings pass it through flagged.

| `rule_code` | Severity | Check |
|---|---|---|
| `UNKNOWN_DISTRICT` | error | name not in `district_aliases` |
| `UNKNOWN_CROP` | error | crop not in the crop master |
| `TYPE_MISMATCH` | error | non-numeric in a numeric column (`NA`, `-`, stray text) |
| `SCHEMA_MISMATCH` | error | expected column missing / unexpected extra column |
| `DUPLICATE_KEY` | error | duplicate on the fact's natural key |
| `OUT_OF_RANGE` | warning | negative or implausible value (yield ≤ 0 or > 1,200 qtl/ha; price ≤ 0 or > 50,000 Rs/qtl) |
| `MISSING_VALUE` | warning | null in a measure column |
| `TOTAL_ROW_IN_DETAIL` | warning | a state/total row mixed with district rows |
| `IDENTITY_MISMATCH` | warning | `area × yield ≠ production` beyond 2% |
| `CROSS_SOURCE_MISMATCH` | info | same measure differs between two DE&S sources |
| `MSP_SUBSTITUTED` | info | paddy price rows (`cell_status = 'provisional'`): these are MSP, not observed prices |

## 6. Reconciliation checks the loader must run and record

These are known-true against the published reports; treat a mismatch as a load failure.

- Price extract: **6,300 rows**; 35 tables × 30 districts × 6 years.
- 2024-25 district crop extract: **5,456 rows**; district sums equal the STATE row for every crop/season/measure;
  `Autumn + Winter + Summer = Total` everywhere.
- 2024-25 land use: **682 rows**; the nine categories sum to `Total area under survey`; surveyed + not-surveyed =
  geographical area.
- State series: **5,632 rows**, 1993-94..2024-25, 14 crops.
- EARAS 2022-23 paddy: state total **40.64 lakh ha, 180.80 lakh MT**.
- EARAS 2023-24 paddy: block file and district file agree at state level: **40.87 lakh ha, 174.83 lakh MT**;
  rice **115.39 lakh MT**.
- Synthetic prices: **90,564 rows**; for every series-year, the monthly mean equals `annual_level_rs_per_quintal`
  within ₹0.01.
- All 30 districts resolve in every district-level source; **zero** `UNKNOWN_DISTRICT` errors on the bundled data.

## 7. Deliverables

```
app/
├── db.py                 DuckDB connection, schema DDL, layer creation
├── masters/              district + crop masters and the deterministic resolver
├── validation/rules.py   the rules in §5, each independently callable
├── ingest/
│   ├── readers.py        per-source readers (BOM, trailing spaces, .dta, year formats)
│   ├── loaders.py        source → raw → staging → analytics, writing dataset_version + lineage_edge
│   └── checks.py         the reconciliation checks in §6
├── api/                  FastAPI: POST /ingest/upload, GET /datasets, /datasets/{id}/validation,
│                         /lineage/{dataset_version_id}, /health
└── cli.py                `python -m app.cli build` → rebuilds data/oiss.duckdb from scratch
tests/                    pytest: the §6 checks, plus one test per validation rule
```

## 8. Acceptance

- `python -m app.cli build` on a clean checkout produces `data/oiss.duckdb` with every check in §6 passing and a
  printed summary of rows per table and findings per rule.
- Re-running produces an identical database (same row counts, same IDs).
- `POST /ingest/upload` with one of the bundled CSVs produces the same findings as the batch loader.
- `POST /ingest/upload` with a deliberately broken copy (unknown district, text in a numeric column, duplicate row)
  returns findings with the right `rule_code`s and quarantines the bad rows without failing the request.
- Every row in `analytics.fact_*` has a non-null `data_origin` and a `dataset_version_id` that resolves.

Ask me before: adding a dependency beyond duckdb/pandas/fastapi/pydantic/pytest; changing any canonical table name;
or inventing data that is not in the sources.
