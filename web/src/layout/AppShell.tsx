/**
 * App shell — DESIGN.md §4.
 *
 * 48px identity band, 232px left nav in demo-flow order, content at 1600px with
 * 24px gutters. No government insignia anywhere: a neutral wordmark only, with
 * the vendor attribution in the footer (DESIGN.md §1).
 */
import { NavLink, Outlet } from 'react-router-dom';

import { useHealth } from '@/api/hooks';
import { Figure, cn } from '@/components/primitives';

interface NavItem {
  to: string;
  label: string;
}

const NAV: NavItem[] = [
  { to: '/ingest', label: 'Ingest' },
  { to: '/lineage', label: 'Storage & lineage' },
  { to: '/dashboard', label: 'Dashboard' },
  { to: '/assistant', label: 'Assistant' },
  { to: '/sandbox', label: 'Sandbox' },
  { to: '/exports', label: 'Exports' },
];

const BUILD_DATE = new Date().toISOString().slice(0, 10);

function BackendStatus() {
  const health = useHealth();

  if (health.isPending) {
    return <span className="text-caption text-white/70">Checking backend…</span>;
  }
  if (health.isError) {
    return (
      <span className="rounded-badge border border-error/50 bg-error-bg px-1.5 py-0.5 text-badge font-medium text-error">
        Backend unavailable
      </span>
    );
  }
  return null;
}

export function AppShell() {
  return (
    <div className="min-h-screen bg-surface-alt">
      <a href="#main" className="skip-link">
        Skip to content
      </a>

      <header className="flex h-band items-center justify-between bg-header px-gutter">
        {/* Neutral wordmark. No state emblem, no DE&S logo (DESIGN.md §1). */}
        <div className="flex items-baseline gap-3">
          <span className="text-section font-semibold text-white">
            Odisha Integrated Statistical System
          </span>
        </div>
        <div className="flex items-center gap-4">
          <BackendStatus />
          <span className="text-caption text-white/70">
            <Figure>{BUILD_DATE}</Figure>
          </span>
        </div>
      </header>

      <div className="flex min-h-below-band">
        <nav
          aria-label="Sections"
          className="w-nav shrink-0 border-r border-line bg-surface"
        >
          <ul className="py-2">
            {NAV.map((item) => (
              <li key={item.to}>
                <NavLink
                  to={item.to}
                  className={({ isActive }) =>
                    cn(
                      'flex items-center justify-between gap-2 border-l-rule px-gutter py-2 text-body transition-colors duration-state',
                      isActive
                        ? 'border-l-primary bg-primary-subtle font-medium text-primary'
                        : 'border-l-transparent text-ink-muted hover:bg-surface-alt hover:text-ink',
                    )
                  }
                >
                  <span>{item.label}</span>
                </NavLink>
              </li>
            ))}
          </ul>
        </nav>

        <div className="min-w-0 flex-1">
          <main id="main" className="mx-auto max-w-content px-gutter py-gutter">
            <Outlet />
          </main>
          <footer className="mx-auto max-w-content px-gutter pb-6 pt-2">
            <p className="border-t border-line pt-3 text-caption text-ink-subtle">
              Prepared by TCS for evaluation. Figures are reproduced from
              Directorate of Economics &amp; Statistics, Odisha publications;
              synthetic series are generated for demonstration and badged
              wherever they appear.
            </p>
          </footer>
        </div>
      </div>
    </div>
  );
}
