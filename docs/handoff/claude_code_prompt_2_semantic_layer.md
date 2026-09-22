# Task 2 for Claude Code — OISS PoC: fix-ups, then the semantic + query layer

Continues from the data layer you just built. Part A is small follow-ups and decisions on the questions you raised.
Part B is the next build: the layer every downstream feature queries — dashboard, GenAI narrative, conversational
assistant, exports. Still a demo: small, fast, no UI.

---

# Part A — decisions and follow-ups

## A1. Dependencies

- **Add `uvicorn`.** A FastAPI service that cannot be served is not a deliverable; my list was the inputs I had in
  mind, not an allowlist.
- **Keep `python-multipart` and `httpx`.** Both are prerequisites of things I asked for (file upload, test client).

## A2. Onion is not a tuber

Add a seventh crop group, `vegetable`, and move onion into it. A DE&S evaluator will notice a bulb filed as a tuber.

## A3. The block→district rollup is the right call — make it visible

Deriving district yield from summed production over summed area is correct (averaging block yields would weight a
50 ha block like a 5,000 ha one), and reproducing 40.64 / 180.80 exactly is the proof. Two conditions:

1. **`grain_source` must propagate** out of `v_district_crop_ayp` into every query response and export, not just live
   in the view. It is a caveat the narrative has to be able to state.
2. **The rollup needs a lineage edge** (`block rows → district aggregate`), so "where did this number come from"
   has an answer in `lineage_edge` rather than only in code.

## A4. Give me the findings breakdown

Print and persist a breakdown of all 10,487 findings by `rule_code` × severity, with a sample row reference for each
code. Reason: if most are `MISSING_VALUE` on crop-season combinations that simply do not exist (wheat in Autumn,
ragi in a coastal district), the validation screen is unreadable at demo time and the number is misleading.

Then split that case out: classify a null measure as **`STRUCTURALLY_ABSENT` (info)** rather than `MISSING_VALUE`
(warning) when the whole (district, crop, season) group has no value in any year of any source — i.e. the crop is not
grown or not priced there — and keep `MISSING_VALUE` for a gap inside an otherwise populated series. Report both
counts separately.

## A5. Two assertions to make permanent

- **No double counting of 2023-24 paddy**, which DE&S publishes at both block and district grain. Add a test that
  asserts the row count and the state total from `v_district_crop_ayp` for 2023-24 paddy, so a future change cannot
  silently double it.
- **The 54 remaining identity mismatches** are said to be publisher rounding on small quantities. Confirm that:
  show them grouped by crop and by magnitude of the underlying area/production. If they cluster in one crop or one
  source rather than at small quantities, it is not rounding and I want to know.

---

# Part B — semantic layer and query API

## B1. Why this shape

Later, an LLM will answer natural-language questions against this data. It must **never** write SQL and never see raw
tables. It will emit a **query spec** — metric, dimensions, filters, period — which you validate against a registry and
compile to parameterised SQL. Everything the RFP asks the assistant to return alongside an answer (applied filters,
source dataset, reporting period, supporting records) then falls out of the spec instead of being reconstructed.
Build that spec and its compiler now; the LLM is a later task.

## B2. Registry (define in code, expose over the API)

**Dimensions** — `district`, `block`, `crop`, `crop_group`, `season`, `agri_year`, `month`, `price_type`,
`land_use_category`, `product`, `data_origin`, `grain_source`.

**Metrics** — each with id, label, unit, formula, allowed grains, default aggregation, and the facts it reads:

| metric_id | Unit | Definition |
|---|---|---|
| `avg_price` | Rs/quintal | mean price over the selected period and grain |
| `price_yoy_pct` | % | year-on-year change in `avg_price` |
| `fhp_wholesale_gap` | Rs/quintal | wholesale minus farm harvest, same district/crop/year |
| `fhp_wholesale_gap_pct` | % | the same as a share of farm harvest price |
| `area` | ha | crop area |
| `production` | qtl | crop production |
| `yield_rate` | qtl/ha | **production ÷ area**, never an average of yields |
| `yield_yoy_pct` | % | year-on-year change in `yield_rate` |
| `production_share_pct` | % | a district's share of the state total |
| `land_use_share_pct` | % | a category's share of area under survey |
| `cropping_area_share_pct` | % | a crop's share of district crop area |

Two rules that matter more than they look: **`yield_rate` is always a ratio of sums**, and **every metric declares the
grains it is valid at** — a query asking for `avg_price` by block must be rejected, not silently answered with
district data.

## B3. Query spec

```jsonc
{
  "metric": "yield_rate",
  "dimensions": ["district", "agri_year"],
  "filters": [{"dimension": "crop", "op": "in", "values": ["CR01"]},
              {"dimension": "season", "op": "eq", "values": ["Winter"]}],
  "period": {"from": "2022-23", "to": "2024-25"},
  "order_by": {"field": "value", "direction": "desc"},
  "limit": 30,
  "include_records": false
}
```

Pydantic-validated against the registry. Unknown metric, dimension, filter value or invalid grain → **HTTP 422 with a
machine-readable error naming the offending field and the allowed values** (the LLM will use that to retry).
No string interpolation into SQL anywhere: parameters only.

## B4. Every response carries its context

```jsonc
{
  "rows": [{"district": "Bargarh", "agri_year": "2024-25", "value": 47.2, "unit": "qtl/ha"}],
  "applied_context": {
    "metric": "yield_rate", "dimensions": [...], "filters": [...], "period": {...},
    "source_datasets": [{"dataset_version_id": "...", "dataset_name": "...", "source_file": "...", "layer": "analytics"}],
    "data_origin": {"official": 1240, "synthetic": 0},
    "grain_source": {"published_district": 900, "aggregated_from_blocks": 340},
    "row_count": 90, "generated_at": "..."
  },
  "caveats": [{"code": "AGGREGATED_FROM_BLOCKS", "severity": "info", "message": "...", "affected_rows": 340}]
}
```

**Caveat engine** — machine-readable, attached by rule to the result set, because the narrative and the assistant will
verbalise these rather than inventing their own:

| code | Trigger |
|---|---|
| `SYNTHETIC_DATA` | any row with `data_origin = 'synthetic'` |
| `PROJECTED_LEVELS` | synthetic rows whose `annual_level_basis = 'projected'` (2019-20 onward) |
| `IMPUTED_LEVELS` | synthetic rows with `annual_level_basis = 'imputed'` |
| `MSP_SUBSTITUTED` | paddy price rows: published figures are Minimum Support Price, not observed prices |
| `AGGREGATED_FROM_BLOCKS` | any row where `grain_source != 'published_district'` |
| `STRUCTURALLY_ABSENT` | requested combinations that do not exist in the source (see A4) |
| `CROSS_SOURCE_MISMATCH` | the measure differs between DE&S sources for the selected scope |
| `PERIOD_GAP` | the requested period spans years with no data (e.g. prices stop at 2018-19 for official rows) |

## B5. Endpoints

```
GET  /semantic/metrics                    registry: metrics with units, grains, definitions
GET  /semantic/dimensions                 registry: dimensions with types and grains
GET  /semantic/dimensions/{id}/values     selectable values (districts, crops, years...), for filters and the LLM
POST /query                               query spec -> rows + applied_context + caveats
POST /query/records                       the supporting records behind a result cell: the underlying fact rows with
                                          dataset_version_id, source_file and cell_status (drill-down)
POST /query/narrative-facts               ONE precomputed fact bundle for a dashboard view: totals, period-on-period
                                          movement, leading and lagging districts, largest changes, anomalies
                                          (> 2 SD from the series mean), plus the caveats above.
                                          Pure SQL, no LLM. This is what the narrative step will be handed later.
GET  /lineage/{dataset_version_id}         already exists — extend to accept a query response's source datasets
```

`/query/narrative-facts` is the single most important endpoint for demo credibility: it is what keeps the GenAI step
from doing arithmetic.

## B6. Determinism and performance

- **Stable ordering**: every query ends with a deterministic tie-break (e.g. `district_id`), so repeated runs and
  screenshots match.
- **Rounding at the edge only**: round in the response, never mid-computation.
- **Target: under 300 ms** for any dashboard query on this data volume. DuckDB views are enough; no caching layer.
  If a query exceeds that, say so rather than adding infrastructure.

## B7. Tests

- **Correctness against published figures**, not self-consistency: `production` for paddy 2023-24 across all districts
  = **174.83 lakh MT**; `yield_rate` for a known district-crop-season matches the published district table;
  `avg_price` for a district-crop-year with official data equals the published value from the price extract.
- `yield_rate` computed as ratio-of-sums ≠ mean-of-yields on a known case, asserting the correct one is used.
- Grain validation: `avg_price` by `block` → 422.
- Unknown metric / dimension / filter value → 422 with allowed values listed.
- Every response's `applied_context.source_datasets` resolves to rows in `dataset_version`.
- Caveats fire: a query on synthetic price years returns `SYNTHETIC_DATA` and `PROJECTED_LEVELS`; a paddy price query
  returns `MSP_SUBSTITUTED`; a 2022-23 paddy district query returns `AGGREGATED_FROM_BLOCKS`; a 2019-20 official
  price query returns `PERIOD_GAP`.
- Determinism: the same spec twice returns identical bytes.

## B8. Out of scope

No UI, no LLM calls, no exports, no crop-yield sandbox adapter. Each is a separate task.

Ask me before: adding a dependency; changing a canonical table name; adding a metric that is not in B2; or inventing
data that is not in the sources.
