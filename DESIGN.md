# OISS PoC — design language

House style for every screen of the DE&S Odisha statistical-data PoC. Task prompts 3, 4, 6 and 7 must follow this
file rather than inventing their own tokens. Derived from the general house style, tightened for a government
statistics audience: **institutional, minimal, dense, legible on a projector.**

## 0. Principles

1. **Official, not commercial.** It should look like an instrument of a statistics directorate — sober, plain, factual.
   No hero sections, no gradients, no illustrations, no marketing voice.
2. **Data first.** Density over whitespace. An evaluator wants to see many rows and several charts at once.
3. **Provenance is part of the design.** Synthetic, analytical-estimate and aggregated data is disclosed as a single
   quiet line in the panel header — once per panel, never beside each figure. The wording is owned by
   `src/lib/provenance.ts` and derived from the backend fields, never typed into a component. See §5.
4. **Nothing decorative moves.** Transitions only for state changes (open, close, load), 120–160 ms, no easing
   flourishes, no animated charts on load.
5. **Accessible by default.** WCAG 2.1 AA contrast, full keyboard operation, visible focus rings, skip-to-content —
   in line with the Guidelines for Indian Government Websites that DE&S itself follows.

## 1. Alignment with the DE&S site — and its limits

The DE&S site (des.odisha.gov.in) is a white page with a deep institutional blue, blue section headings, white cards
with thin borders, and a plain top identity band. We follow that register: **deep blue as the single institutional
colour, white surfaces, restrained borders, square-ish corners.**

Before building, open the DE&S site and sample the exact blue with a colour picker, then replace `--color-primary`
below. The values here are close but were not sampled from the live site.

**Do not reproduce the Odisha State Emblem, the DE&S logo, or any government insignia.** This is a vendor demo, not
a government site; borrowing official marks implies endorsement. Use a neutral wordmark: "Odisha Integrated
Statistical System — Proof of Concept", with "Prepared by TCS for evaluation" in the footer.

## 2. Tokens

```css
:root {
  /* Institutional */
  --color-primary:        #12508F;   /* deep blue: nav, primary buttons, links, active state */
  --color-primary-hover:  #0E4272;
  --color-primary-subtle: #EAF1F8;   /* selected rows, active nav background */
  --color-header:         #0C3556;   /* top identity band */

  /* Neutrals */
  --color-text:           #0F172A;
  --color-text-muted:     #475569;
  --color-text-subtle:    #64748B;   /* lightest text permitted on white */
  --color-border:         #D7DEE7;
  --color-border-strong:  #A9B4C2;
  --color-surface:        #FFFFFF;
  --color-surface-alt:    #F6F8FA;   /* table header, page background behind cards */

  /* Status */
  --color-error:          #B42318;  --color-error-bg:   #FEF3F2;
  --color-warning:        #B54708;  --color-warning-bg: #FFFAEB;
  --color-info:           #0B5A8A;  --color-info-bg:    #EFF8FF;
  --color-success:        #1B7F4B;  --color-success-bg: #ECFDF3;

  /* Provenance — reserved, never reused for anything else */
  --prov-synthetic:       #8A4B08;  --prov-synthetic-bg:  #FEF6EB;  --prov-synthetic-border:  #EEC08A;
  --prov-estimate:        #5B21B6;  --prov-estimate-bg:   #F5F3FF;  --prov-estimate-border:   #DDD6FE;
  --prov-aggregated:      #334155;  --prov-aggregated-bg: #F1F5F9;  --prov-aggregated-border: #CBD5E1;

  /* Layout */
  --radius:      4px;        /* 6px for cards; nothing rounder */
  --shadow-card: 0 1px 2px rgba(15,23,42,.06);
  --nav-width:   232px;
  --content-max: 1600px;
}
```

**Chart palette — Okabe–Ito, colour-blind safe and projector-safe.** Use in this order, maximum 8 series:

```
#0072B2  #E69F00  #009E73  #CC79A7  #56B4E9  #D55E00  #8C6D1F  #4D4D4D
```

Never reuse a provenance or status colour for a data series. Never let colour alone carry meaning: pair it with a
label, a pattern, or a direct annotation.

## 3. Typography

- **Family:** Inter (fallback: `system-ui, "Segoe UI", sans-serif`). One family throughout.
- **Numbers:** `font-variant-numeric: tabular-nums` on every figure, table cell, KPI and axis label. Non-negotiable —
  columns of figures must align.
- **Scale:** 12 (captions, chart labels) · 14 (body, table) · 16 (section text) · 20 (card titles) · 24 (page title) ·
  30 (KPI value). Line height 1.45 for text, 1.2 for figures.
- **Weights:** 400 body, 500 labels and table headers, 600 titles and KPI values. Never 700+.
- **Case:** sentence case everywhere. No all-caps except short table headers (12px, letter-spacing .04em).
- **Voice:** factual and impersonal. "Winter paddy yield, 2024-25", not "Let's look at winter paddy!".

## 4. Layout

- **Identity band** (48px, `--color-header`): system name left, environment tag and build date right.
- **Left nav** (232px): the demo flow in order — Ingest · Storage & lineage · Dashboard · Assistant · Sandbox ·
  Exports. Active item uses `--color-primary-subtle` with a 3px left rule in `--color-primary`.
- **Content**: max 1600px, 24px gutters, 16px grid gap. Cards are white, 1px `--color-border`, 6px radius,
  `--shadow-card`; 16px padding, 20px for chart cards.
- **Filter bar**: sticky under the page title. Below it, always, the applied-context strip (sources, period, row
  count, data-origin mix) and the caveat list. These are part of the layout, not an afterthought.
- **Tables**: 36px rows (32px compact), header `--color-surface-alt` with a bottom border, right-aligned numerics,
  left-aligned text, zebra striping off, hover highlight on, sticky header on long grids.
- **Drawers** (drill-down, record detail) slide from the right at 560px; modals only for destructive confirmations.

## 5. Provenance and status components

Provenance is disclosed **once per panel**, not once per figure. A column of numbers each wearing its own chip is
unreadable, and the statement belongs to the panel rather than to any single value.

| Component | Use | Style |
|---|---|---|
| `ProvenanceNote` | synthetic, model or block-aggregated data anywhere in the panel | 11px, 400 weight, `text-ink-subtle`; no chip, no border, no icon |
| `Severity chip` | validation findings: error / warning / info | status tokens |
| `CaveatList` | the backend `caveats` array, plain language, with affected-row counts | info background, left rule |

### ProvenanceNote

One quiet line in the panel header, directly under the title. Never beside a figure, never inside a table cell,
never over a chart. Where more than one condition applies the lines join with ` · ` and stay on one line. A panel
whose data is wholly official and published at its stated grain renders nothing — silence is the correct disclosure
for an unremarkable panel.

The three wordings, which are fixed:

| Condition | Line |
|---|---|
| `data_origin` includes `synthetic` | Representative dataset modelled on DE&S Price Statistics, 2013-19 |
| `data_origin` includes `model` | Analytical estimates |
| `grain_source` includes `aggregated_from_blocks` | District figures aggregated from block-level data |

**The wording is derived, never typed into a component.** `src/lib/provenance.ts` owns the strings and maps them
from the backend fields `data_origin`, `annual_level_basis` and `grain_source`; `ProvenanceNote` renders whatever
that returns. A component that hard-codes one of these sentences is a bug. Panels reading mocked data carry the same
field shape, so they disclose identically once wired to a real endpoint.

The reserved provenance colours in §2 remain reserved — they are still never reused for a data series or a status —
but they are no longer painted onto per-figure chips.

Status chips are unchanged: 11px, 500 weight, 2px radius, 1px border, uppercase-free, and severity is never carried
by colour alone — the word is always present.

## 6. Charts (Recharts)

- Axes always labelled with units. Grid lines `--color-border` at 50% opacity, horizontal only.
- Direct series labels where space allows; legends only when more than three series.
- 12px labels minimum. Numbers use the same tabular figures as tables.
- **Nulls are gaps, not zeros.** Mark structurally absent combinations in the empty state, not as a value.
- **Official versus synthetic** on a time axis: solid line for official, dashed for synthetic, with a labelled
  boundary rule at 2018-19. This single convention carries most of the honesty story.
- Tooltips show the value and the unit. Provenance is stated once in the panel header, not repeated per point.

## 7. States

- **Loading:** skeletons matching final layout; never a full-page spinner; never a jump on load.
- **Empty:** say what is missing and why ("Not grown in this district", "Official price data ends at 2018-19").
  Never an empty chart that reads as zero.
- **Error:** what failed, what still works, and a retry. No stack traces, no white screens.
- **Disabled:** explain why in a tooltip, e.g. "Average price requires a data origin to be selected".

## 8. Projector reality

Design against 1366×768 with a washed-out projector: 14px minimum body text, no grey below `--color-text-subtle` on
white, no hairline borders under 1px, no thin-weight type. Check every screen once at reduced brightness.

**Light mode only.** Dark mode is a second surface to get right for no evaluation benefit.

## 9. Tailwind

Map these tokens in `tailwind.config.js` (`theme.extend.colors`, `fontSize`, `spacing`, `borderRadius`) and use the
mapped names. No arbitrary values like `text-[#12508F]` in components — if a value is missing, add it to the theme.
