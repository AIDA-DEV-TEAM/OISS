import { useState } from 'react';

import type { AppliedContext, Caveat, QuerySpec } from '@/api/client';
import { AppliedContextStrip, QueryContextStrip } from '@/components/AppliedContextStrip';
import { PageHeader } from '@/components/PageHeader';
import { CaveatList } from '@/components/provenance';
import { DashboardFilterBar } from '@/features/dashboard/DashboardFilterBar';
import { DrillDownDrawer } from '@/features/dashboard/DrillDownDrawer';
import { ExportModal } from '@/components/ExportModal';
import { AgricultureDashboard } from '@/features/dashboard/agriculture/AgricultureDashboard';
import { PriceDashboard } from '@/features/dashboard/price/PriceDashboard';
import { useDashboardFilters } from '@/features/dashboard/useDashboardFilters';
import { contextFromApplied } from '@/lib/exportContext';

export function DashboardPage() {
  const { filters, updateFilters, resetFilters } = useDashboardFilters();

  // Active query context and caveats for the applied-context strip
  const [activeContext, setActiveContext] = useState<AppliedContext | null>(null);
  const [activeCaveats, setActiveCaveats] = useState<Caveat[]>([]);

  // Drill-down drawer state
  const [drillDownSpec, setDrillDownSpec] = useState<QuerySpec | null>(null);
  const [drillDownTitle, setDrillDownTitle] = useState('');
  const [drawerOpen, setDrawerOpen] = useState(false);

  // Export modal state (Task 5 stub)
  const [exportOpen, setExportOpen] = useState(false);
  const [exportTitle, setExportTitle] = useState('');

  const handleDrillDown = (spec: QuerySpec, title: string) => {
    setDrillDownSpec(spec);
    setDrillDownTitle(title);
    setDrawerOpen(true);
  };

  const handleExport = (title: string) => {
    setExportTitle(title);
    setExportOpen(true);
  };

  const handleContextUpdate = (context: AppliedContext, caveats: Caveat[]) => {
    setActiveContext(context);
    setActiveCaveats(caveats);
  };

  return (
    <div className="flex flex-col min-h-full">
      {/* Page Header */}
      <PageHeader
        title="Interactive Analytics Dashboard"
        description="Explore Odisha agricultural price statistics and EARAS crop estimates across 30 districts and 32 years of historical series."
      />

      {/* Sticky Filter Bar */}
      <DashboardFilterBar
        filters={filters}
        onUpdate={updateFilters}
        onReset={resetFilters}
      />

      {/* Applied Context Strip and Caveats */}
      <div className="flex flex-col gap-3 px-gutter py-3 bg-surface border-b border-line">
        {activeContext ? (
          <QueryContextStrip context={activeContext} />
        ) : (
          <AppliedContextStrip
            sources={[]}
            period={`${filters.from} to ${filters.to}`}
          />
        )}

        {activeCaveats.length > 0 && (
          <div className="mt-1">
            <CaveatList caveats={activeCaveats} />
          </div>
        )}
      </div>

      {/* Main Content Area */}
      <main className="flex-1 px-gutter py-6 bg-surface-alt">
        {filters.view === 'price' ? (
          <PriceDashboard
            filters={filters}
            onDrillDown={handleDrillDown}
            onExport={handleExport}
            onContextUpdate={handleContextUpdate}
          />
        ) : (
          <AgricultureDashboard
            filters={filters}
            onDrillDown={handleDrillDown}
            onExport={handleExport}
            onUpdateFilters={updateFilters}
            onContextUpdate={handleContextUpdate}
          />
        )}
      </main>

      {/* Drill-Down Fact Records Drawer */}
      <DrillDownDrawer
        open={drawerOpen}
        onClose={() => setDrawerOpen(false)}
        title={drillDownTitle}
        querySpec={drillDownSpec}
      />

      <ExportModal
        open={exportOpen}
        onClose={() => setExportOpen(false)}
        exportType="dashboard_panel"
        context={contextFromApplied(exportTitle, activeContext, activeCaveats)}
      />
    </div>
  );
}
