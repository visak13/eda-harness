import { Navigate, useLocation } from "react-router";
import type { RouteObject } from "react-router";
import { AppShell } from "./components/AppShell";
import { RecordsPage } from "./pages/Records";
import { SettingsPage } from "./pages/Settings";
import {
  ArtifactPage,
  DecisionsPage,
  DocPage,
  EpicPage,
  EpicsPage,
  LibraryPage,
  NotFoundPage,
  SeatsPage,
  TicketPage,
} from "./pages";

// Redirects preserve the query string so ?as= survives (parity with the legacy `_qs`).
function RedirectTo({ to }: { to: string }): React.JSX.Element {
  const { search } = useLocation();
  return <Navigate to={`${to}${search}`} replace />;
}

// The ONE route table. main.tsx mounts it under the Vite base; src/test/deadControls.test.tsx walks
// it (human #26) so every destination is linted for dead controls — add a page here, it is linted.
export const appRoutes: RouteObject[] = [
  {
    path: "/",
    element: <AppShell />,
    children: [
      { index: true, element: <RedirectTo to="/me" /> },
      { path: "me", element: <DecisionsPage /> },
      { path: "epics", element: <EpicsPage /> },
      { path: "epic/:id", element: <EpicPage /> },
      { path: "ticket/:id", element: <TicketPage /> },
      { path: "doc/:id", element: <DocPage /> },
      { path: "records/:id", element: <RecordsPage /> },
      { path: "artifact/:id", element: <ArtifactPage /> },
      { path: "seats", element: <SeatsPage /> },
      { path: "settings", element: <SettingsPage /> },
      { path: "library", element: <RedirectTo to="/library/knowledge" /> },
      { path: "library/:section", element: <LibraryPage /> },
      // Legacy paths keep their shape but redirect to Library (preserving ?as=).
      { path: "tickets", element: <RedirectTo to="/library/tickets" /> },
      { path: "activity", element: <RedirectTo to="/library/history" /> },
      { path: "*", element: <NotFoundPage /> },
    ],
  },
];
