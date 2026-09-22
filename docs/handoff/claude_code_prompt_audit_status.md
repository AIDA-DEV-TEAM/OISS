# Task 0 (run this first after a break) — audit what exists and report status

Read `00_project_context.md` first, then the task prompts in `docs/handoff/` (tasks 1–8).

Work on this project has been done by more than one assistant across several sessions, and the record of who built
what is incomplete. **Before writing any new code, establish the truth of the repository and report it.**

## Rules for this task

- **Read-only.** Do not add features, refactor, reformat, fix bugs, or "tidy" anything. Running the test suite, the
  build and read-only queries is expected; changing files is not. The one exception is writing `docs/STATUS.md` at
  the end.
- **Evidence over inference.** Every claim in your report cites a file path, a test name, a command output or a query
  result. If you cannot verify something, say "unverified" rather than assuming it works.
- **Distinguish three states per item**: `done` (verified), `partial` (exists but fails its acceptance criteria or is
  incomplete), `missing`.

## 1. Inventory

- Repository tree (excluding `.venv`, `node_modules`, `data/raw`), with file sizes and last-modified dates.
- `git log --oneline --stat` summarised: what changed, when, in what order. Branch and working-tree state, including
  uncommitted or untracked files, and any stashes.
- Python dependencies actually installed versus those declared; same for `web/package.json` if it exists.
- Whether `data/oiss.duckdb` exists, when it was built, and its table list with row counts.

## 2. Verify each task against its acceptance criteria

For tasks 1–8, read the corresponding prompt in `docs/handoff/` and check what it required. Report per task:
status, what exists, what is missing, and the evidence.

Specific checks worth running, because these numbers are known to be correct:

**Task 1 — data layer**
- `python -m app.cli build` runs clean; 23/23 reconciliation checks pass; a rebuild is byte-identical.
- Row counts: `fact_price` 96,864 · `fact_crop_ayp` 17,952 · `fact_land_use` 8,916 · `fact_state_series` 5,632 ·
  `dim_district` 30 · `dim_crop` 23 · `dim_block` 344 · `dim_period` 185.
- Governance tables populated: `dataset_version`, `lineage_edge`, `validation_finding`, `load_run`.
- Findings split: `STRUCTURALLY_ABSENT` 7,473 info · `MISSING_VALUE` 2,063 · `UNKNOWN_BLOCK` 351 ·
  `MSP_SUBSTITUTED` 319 · `TOTAL_ROW_IN_DETAIL` 225 · `IDENTITY_MISMATCH` 54 · `OUT_OF_RANGE` 2.

**Task 2 — semantic layer**
- Registry has 11 metrics and 12 dimensions; `/query`, `/query/records`, `/query/narrative-facts`,
  `/semantic/*` respond.
- Known-good values: paddy production 180.80 / 174.83 / 176.23 lakh MT for 2022-23 / 2023-24 / 2024-25;
  Bargarh Winter paddy 2024-25 yield 55.73; Balangir paddy farm-harvest price 2015-16 ₹1,410;
  `yield_rate` returns 42.273 (ratio of sums), not 39.194 (mean of yields).
- Guards still in place: AYP relations pin `period_type = 'season'` (otherwise annual figures double);
  an unpinned price query returns 422 `unpinned_scope`; anomalies report their axis (`cross_district` /
  `time_series`).
- Caveats fire: `SYNTHETIC_DATA`, `PROJECTED_LEVELS`, `MSP_SUBSTITUTED`, `AGGREGATED_FROM_BLOCKS`,
  `STRUCTURALLY_ABSENT`, `CROSS_SOURCE_MISMATCH`, `PERIOD_GAP`.

**Task 3 — frontend foundation, ingest and lineage screens**
- `web/` exists; `npm run build` clean; types generated from the backend OpenAPI spec rather than hand-written.
- **Design conformance against `web/DESIGN.md`**: tokens mapped in `tailwind.config.js`; no hex literals or arbitrary
  Tailwind values in components; tabular figures on numbers; the three provenance badges exist and are
  backend-driven; light mode only; no government insignia used.
- Validation screen defaults to errors and warnings with `STRUCTURALLY_ABSENT` behind a toggle.
- Lineage graph renders `lineage_edge`, including the 2022-23 paddy block→district rollup edge.

**Tasks 4–8** — check against their prompts: dashboards and drill-down; export service in five formats carrying
applied context; grounded narrative and assistant (LLM emits query specs only, numbers validated against the fact
bundle, cached responses); sandbox adapter and wizard with the Analytical Estimates label and publish-to-dashboard;
integration, demo seed, demo script and documentation.

## 3. Report divergences, not just gaps

Different assistants make different choices. Flag anything that departs from the prompts or from what earlier work
established, and say which you believe is better and why:

- Table, column, endpoint or component names that differ from the prompts.
- A second implementation of something that already exists (a validation path, a query builder, a formatter).
- Dependencies added beyond duckdb / pandas / fastapi / pydantic / uvicorn / pytest / python-multipart / httpx and
  the declared frontend stack.
- **Any code path where an LLM output could reach the database, or where a number displayed to the user is not
  computed in SQL.** This is the project's hard rule; check it specifically.
- Any place `data_origin`, `annual_level_basis`, `grain_source` or caveats are dropped between layers.
- Dead code, TODOs, commented-out blocks, and tests that are skipped or trivially passing.

## 4. Deliverable

Write `docs/STATUS.md` containing:

1. **One-paragraph summary**: where the project stands.
2. **Status table**: task 1–8 × `done` / `partial` / `missing`, with the evidence for each.
3. **Verification results**: every check above, expected versus actual.
4. **Divergences and risks**, ordered by how much they would cost to fix later.
5. **Resume plan**: the next three concrete pieces of work in order, with the task prompt each belongs to, and an
   explicit statement of what must be re-verified before building on partial work.
6. **Commands to reproduce** every check you ran.

Then stop and wait. Do not start the resume plan in this session.
