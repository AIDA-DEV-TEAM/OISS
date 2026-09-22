import { Navigate, createBrowserRouter } from 'react-router-dom';

import { AppShell } from '@/layout/AppShell';
import { DashboardPage } from '@/pages/DashboardPage';
import { IngestPage } from '@/pages/IngestPage';
import { LineagePage } from '@/pages/LineagePage';
import { AssistantPage } from '@/pages/AssistantPage';
import { ExportsPage } from '@/pages/ExportsPage';
import { SandboxPage } from '@/pages/SandboxPage';

export const router = createBrowserRouter(
  [
    {
      path: '/',
      element: <AppShell />,
      children: [
        { index: true, element: <Navigate to="/ingest" replace /> },
        { path: 'ingest', element: <IngestPage /> },
        { path: 'lineage', element: <LineagePage /> },
        { path: 'dashboard', element: <DashboardPage /> },
        { path: 'assistant', element: <AssistantPage /> },
        { path: 'sandbox', element: <SandboxPage /> },
        { path: 'exports', element: <ExportsPage /> },
      ],
    },
  ],
  // Opt in to the v7 behaviours now so the console stays clean and the
  // upgrade is not a behaviour change later.
  { future: { v7_relativeSplatPath: true } },
);
