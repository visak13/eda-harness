import { Navigate, useLocation } from "react-router";
import type { RouteObject } from "react-router";
import { AppShell } from "./components/AppShell";
import { RecordsPage } from "./pages/Records";
import { SettingsPage } from "./pages/Settings";
import { AdminPage } from "./pages/admin/Admin";
import { JoinPage } from "./pages/admin/Join";
import { SetupPage } from "./pages/admin/Setup";
import {
  ArtifactPage,
  DecisionsPage,
  DocPage,
  EpicPage,
  EpicsPage,
  LibraryPage,
  TopicPage,
  NotFoundPage,
  SeatsPage,
  TicketPage,
  CodePage,
  CodeFaqPage,
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
      // S6 (design-e963c656f5 §4.8): the Admin console, admins only (the page says so to anyone else)
      { path: "admin", element: <AdminPage /> },
      // epic-91fcd3b370 S3: the Code tab (full-bleed; AppShell collapses the rail) and its FAQ
      { path: "code", element: <CodePage /> },
      { path: "code/faq", element: <CodeFaqPage /> },
      { path: "library", element: <RedirectTo to="/library/knowledge" /> },
      { path: "library/:section", element: <LibraryPage /> },
      { path: "library/topics/:id", element: <TopicPage /> },
      // Legacy paths keep their shape but redirect to Library (preserving ?as=).
      { path: "tickets", element: <RedirectTo to="/library/tickets" /> },
      { path: "activity", element: <RedirectTo to="/library/history" /> },
      { path: "*", element: <NotFoundPage /> },
    ],
  },
  // S6: the teammate invite landing and the first-run wizard stand outside the shell (no session yet)
  { path: "/join", element: <JoinPage /> },
  { path: "/setup", element: <SetupPage /> },
];
