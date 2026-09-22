# Task 4 — interactive analytics dashboard (RFP area 3)

Read `00_project_context.md` first. Backend on 8001, frontend foundation from task 3 in `web/`.

The dashboard is the centre of the demo. **Price Statistics is the primary dashboard; Agriculture/EARAS is the
secondary view.** Every figure comes from `POST /query`; the frontend performs no arithmetic beyond formatting.

## 1. Shared dashboard frame

- **Filter bar**: agricultural year range, district (multi), crop (multi), season, price type. Filters are URL state,
  so any view is shareable and reproducible in a rehearsal.
- **Applied-context strip** under the filters: source datasets, period, row count, data-origin mix, and the
  `CaveatList`. This is what makes the demo defensible — it is always visible, never hidden behind a tooltip.
- **Every chart and table supports drill-down**: clicking a bar, point or row opens a drawer that calls
  `POST /query/records` and shows the underlying fact rows with dataset version, source file and cell status.
- **Export button on every panel**, wired to the export service in task 5 (stub the call until then).

## 2. Price dashboard (primary)

- **KPI cards**: average price for the selection, year-on-year change, the farm-harvest-to-wholesale gap, number of
  districts and crops in scope. Each KPI shows its unit and badges synthetic contributions.
- **Trend chart**: monthly price over time, one line per selected crop or district, with a visible break or shading
  where official data ends (2018-19) and synthetic data begins.
- **District comparison**: ranked bar chart of average price by district for the selected crop and period, with
  leading and lagging districts highlighted.
- **Crop comparison**: same, across crops.
- **Farm harvest vs wholesale**: paired view for the 13 crops with both, showing the gap in rupees and per cent.
- **Records grid**: the filtered rows with pagination, sorting and column visibility.
- **Paddy must display the MSP caveat** wherever paddy prices appear.

## 3. Agriculture dashboard (secondary)

- **KPI cards**: total area, total production, state yield rate (production ÷ area, never an average of yields).
- **District comparison** of yield and production for a crop and season, with `Aggregated from blocks` badges where
  relevant.
- **Long-run state series**: 1993-94 to 2024-25 from `fact_state_series` — the strongest single visual in the demo,
  because it is 32 years of genuine DE&S data.
- **Land-use composition** for a district: the nine-fold split, with shares.
- **Actual vs forecast panel**, empty until the sandbox publishes results (task 7). Show an explicit empty state
  rather than hiding the panel.

## 4. Rules

- **Never average an average.** Rates come from the backend as ratios of sums.
- **Units are always displayed** and never mixed silently in one chart (ha vs '000 ha, qtl vs '000 MT).
- **Null is not zero.** Gaps render as gaps; `STRUCTURALLY_ABSENT` combinations say "not grown / not priced here".
- **Colour never carries meaning alone** — pair it with a label or shape.
- Charts must be legible on a projector: axis labels, no tiny fonts, no more than ~8 series.

## 5. Tests

- Component tests for KPI and chart panels against fixture responses.
- One end-to-end path: set filters → KPIs update → click a bar → drawer shows records with a dataset version.
- Assert a known figure end to end: paddy production 2023-24 across all districts renders as **174.83 lakh MT**.
