# Task 3 — frontend foundation + ingestion, validation and lineage screens (RFP areas 1 and 2)

Read `00_project_context.md` first. Backend from tasks 1–2 is running on port 8001.

Build the React app shell and the first two screens of the demo flow. This is the first thing an evaluator sees, and
it establishes the component library every later screen reuses.

## 0. Design language — follow `web/DESIGN.md`

**`web/DESIGN.md` is the house style for this project and is already written. Read it before writing any component,
and follow it exactly. Do not invent a palette, a type scale, spacing, radii or chart colours, and do not restyle
anything it specifies.** It defines the institutional palette derived from the DE&S Odisha site, the typography
(including tabular figures on every number), layout and density, the reserved provenance colours, the Okabe–Ito chart
palette, and the state/empty/error conventions.

Your job in this task is to **implement** it:

- Map every token in §2 of that file into `tailwind.config.js` (`theme.extend.colors`, `fontSize`, `spacing`,
  `borderRadius`, `boxShadow`) and use the mapped names in components. **No arbitrary values** such as
  `text-[#12508F]`; if something is missing, add it to the theme.
- Put the CSS custom properties in a single `web/src/styles/tokens.css`, imported once.
- Build the shared components §4 and §5 of that file imply, and use them everywhere rather than restyling per screen.
- If a requirement here and `DESIGN.md` appear to conflict, `DESIGN.md` wins; flag the conflict rather than
  resolving it silently.
- Two rules from it that are easy to miss and hard to retrofit: `font-variant-numeric: tabular-nums` on every figure,
  and **no government insignia** — neutral wordmark only, with "Prepared by TCS for evaluation" in the footer.

## 1. Foundation

- **Vite + React + TypeScript + Tailwind + Recharts** in `web/`. React Router. TanStack Query for data fetching.
- **Generate TypeScript types from the backend's OpenAPI spec** (`openapi-typescript` against
  `http://localhost:8001/openapi.json`), committed to `web/src/api/types.ts`. Never hand-write request or response
  types; a backend change must surface as a compile error.
- **App shell**: identity band and left navigation exactly as `DESIGN.md` §4 describes, following the demo flow —
  Ingest → Storage & Lineage → Dashboard → Assistant → Sandbox → Exports. Later screens are placeholders for now.
- **Shared component library** in `web/src/components/`, styled only from the tokens: `Card`, `DataTable`,
  `StatCard`, `Badge`, `SeverityChip`, `CaveatList`, `EmptyState`, `ErrorState`, `LoadingState`, `Drawer`,
  `AppliedContextStrip`. Keyboard-navigable tables, visible focus rings, sensible focus order.
- **The three provenance badges** (`DESIGN.md` §5), driven by backend fields, never hard-coded:
  `Synthetic` (tooltip naming the basis: published / imputed / projected), `Analytical Estimate`,
  `Aggregated from blocks`.
- **`CaveatList`** renders the backend's `caveats` array. Every screen showing figures renders it.
- **Global error and empty states**: if the backend is down, show a clear message. Never render an empty chart as if
  it were zero.

## 2. Screen: Ingest and validate (RFP area 1)

- **Upload** CSV or Excel (drag-and-drop plus file picker) to `POST /ingest/upload`.
- **Schema preview**: detected columns, inferred types, row count, first N rows.
- **Validation results**: findings grouped by `rule_code` with severity chips, counts, and expandable row-level
  detail showing the offending value and the series it belongs to.
  **Default the view to errors and warnings only.** On the bundled data that is 2,695 findings; the 7,473
  `STRUCTURALLY_ABSENT` info findings (combinations that do not exist — a crop not grown or not priced in that
  district) sit behind a toggle labelled so the distinction is obvious. Showing that the system separates
  "structurally absent" from "missing" is a point in the demo's favour, so make the toggle visible, not buried.
- **Ingestion status and dataset metadata**: dataset name, source file, SHA-256, row count, layer, load time,
  version id.
- **Quarantine view**: rows that failed an error rule, with the reason per row.
- A **"use a bundled dataset" option** so the demo can run without a file to hand: list the loaded datasets and show
  their stored findings through the same UI.

## 3. Screen: Storage and lineage (RFP area 2)

- **Layer view**: Raw / Landing → Validation / Quarantine → Cleansed / Staging → Analytics-Ready, showing row counts
  per layer for the selected dataset and what happened between layers.
- **Dataset detail**: versions with load time, row count, checksum; the validation summary for that version.
- **Lineage graph**: render `lineage_edge` as a directed graph from source file through layers to analytics tables
  and exports. Clicking a node shows its dataset version. Use a lightweight renderer (React Flow if a dependency is
  acceptable; otherwise SVG). Keep the layout deterministic so it looks the same in every run-through.
- **The 2022-23 paddy rollup must be visible in the graph** (block rows → district aggregate), since a reviewer may
  ask where district paddy came from for that year.

## 4. Quality bar

- No fabricated placeholder data anywhere — no lorem ipsum, no fake rows, no invented districts.
- Loading states for everything asynchronous; nothing jumps.
- Works at 1366×768 (typical projector) and above; check once at reduced brightness (`DESIGN.md` §8).
- `npm run build` clean, no TypeScript errors, no console errors in normal use.
- **Design conformance**: no hex literals or arbitrary Tailwind values outside `tailwind.config.js` and
  `tokens.css`; every number rendered with tabular figures; light mode only.

## 5. Out of scope

Dashboard charts, GenAI, assistant, sandbox and exports. Their nav entries are placeholders.
