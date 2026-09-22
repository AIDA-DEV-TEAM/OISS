/** Tailwind theme — DESIGN.md §9.
 *
 * Every value here mirrors a token in src/styles/tokens.css. Components use the
 * mapped names only: no arbitrary values such as text-[#12508F]. If something
 * is missing, it is added here rather than inlined.
 *
 * Naming note: DESIGN.md's --color-text* map to `ink*` and --color-border* to
 * `line*`, because `text-text-muted` and `border-border` do not read. The raw
 * values are unchanged.
 *
 * @type {import('tailwindcss').Config}
 */
export default {
  content: ['./index.html', './src/**/*.{ts,tsx}'],
  // DESIGN.md §8: light mode only. Dark mode is deliberately not implemented.
  darkMode: 'media',
  theme: {
    extend: {
      colors: {
        primary: {
          DEFAULT: 'var(--color-primary)',
          hover: 'var(--color-primary-hover)',
          subtle: 'var(--color-primary-subtle)',
        },
        header: 'var(--color-header)',

        ink: {
          DEFAULT: 'var(--color-text)',
          muted: 'var(--color-text-muted)',
          subtle: 'var(--color-text-subtle)',
        },
        line: {
          DEFAULT: 'var(--color-border)',
          strong: 'var(--color-border-strong)',
        },
        surface: {
          DEFAULT: 'var(--color-surface)',
          alt: 'var(--color-surface-alt)',
        },

        error: { DEFAULT: 'var(--color-error)', bg: 'var(--color-error-bg)' },
        warning: { DEFAULT: 'var(--color-warning)', bg: 'var(--color-warning-bg)' },
        info: { DEFAULT: 'var(--color-info)', bg: 'var(--color-info-bg)' },
        success: { DEFAULT: 'var(--color-success)', bg: 'var(--color-success-bg)' },

        // Reserved for provenance. Never used for a data series or a status.
        synthetic: {
          DEFAULT: 'var(--prov-synthetic)',
          bg: 'var(--prov-synthetic-bg)',
          border: 'var(--prov-synthetic-border)',
        },
        estimate: {
          DEFAULT: 'var(--prov-estimate)',
          bg: 'var(--prov-estimate-bg)',
          border: 'var(--prov-estimate-border)',
        },
        aggregated: {
          DEFAULT: 'var(--prov-aggregated)',
          bg: 'var(--prov-aggregated-bg)',
          border: 'var(--prov-aggregated-border)',
        },

        chart: {
          1: 'var(--chart-1)',
          2: 'var(--chart-2)',
          3: 'var(--chart-3)',
          4: 'var(--chart-4)',
          5: 'var(--chart-5)',
          6: 'var(--chart-6)',
          7: 'var(--chart-7)',
          8: 'var(--chart-8)',
        },
      },

      // DESIGN.md §3: 12 · 14 · 16 · 20 · 24 · 30, plus 11 for badges.
      // Line height 1.45 for text, 1.2 for figures.
      fontSize: {
        badge: ['11px', { lineHeight: '1.2', fontWeight: '500' }],
        caption: ['12px', { lineHeight: '1.45' }],
        body: ['14px', { lineHeight: '1.45' }],
        section: ['16px', { lineHeight: '1.45' }],
        title: ['20px', { lineHeight: '1.3' }],
        page: ['24px', { lineHeight: '1.2' }],
        kpi: ['30px', { lineHeight: '1.2' }],
      },

      fontFamily: {
        sans: ['Inter', 'system-ui', '"Segoe UI"', 'sans-serif'],
      },

      // DESIGN.md §4: nav 232px, content 1600px, band 48px, rows 36/32px,
      // drawer 560px, gutters 24px, grid gap 16px, card padding 16/20px.
      spacing: {
        band: '48px',
        nav: '232px',
        row: '36px',
        'row-compact': '32px',
        drawer: '560px',
        gutter: '24px',
        card: '16px',
        'card-chart': '20px',
      },
      maxWidth: {
        content: 'var(--content-max)',
      },
      minHeight: {
        // Viewport less the 48px identity band.
        'below-band': 'calc(100vh - 48px)',
      },
      maxHeight: {
        // A centred dialog stays clear of the viewport edges.
        dialog: '90vh',
        // Scroll containers inside a dialog or drawer.
        panel: '320px',
      },
      // DESIGN.md §3: the only permitted all-caps, at 12px.
      letterSpacing: {
        header: '0.04em',
      },
      borderWidth: {
        // The 3px left rule on active nav items, caveats and layer cards.
        rule: '3px',
      },
      borderRadius: {
        DEFAULT: 'var(--radius)',
        card: '6px',
        badge: '2px',
      },
      boxShadow: {
        card: 'var(--shadow-card)',
        drawer: '-4px 0 16px rgba(15, 23, 42, 0.10)',
      },

      // DESIGN.md §0.4: state changes only, 120–160ms, no easing flourish.
      transitionDuration: {
        state: '140ms',
      },
    },
  },
  plugins: [],
};
