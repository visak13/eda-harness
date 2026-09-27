import { lazy, Suspense } from "react";
import { Navigate, useLocation } from "react-router";
import type { RouteObject } from "react-router";
import { AppShell } from "./components/AppShell";
import { PageError } from "./components/PageError";
import ui from "./components/ui.module.css";
import { EpicsPage } from "./pages/Epics";
import { NotFoundPage } from "./pages";

// S22 (performance pass): the landing page (Epics) is in the entry bundle; every other page is its own chunk,
// fetched on first visit. The single 896 kB bundle held Admin, Design, Code, Library, Settings, …
// for a first paint that shows none of them. `handle.preload` starts a page's chunk early: main.tsx calls it for
// the route matched at boot, so a cold /admin fetches its chunk alongside whoami instead of after it (a waterfall
// the trace measured at ~120 ms of settle time).
export type PageHandle = { preload?: () => Promise<unknown> };

function page<K extends string>(load: () => Promise<Record<K, React.ComponentType>>, name: K):
    { element: React.JSX.Element; handle: PageHandle } {
  let loading: Promise<Record<K, React.ComponentType>> | undefined;
  let loaded: React.ComponentType | undefined;
  const once = () => (loading ??= load().then(
    (m) => { loaded = m[name] as React.ComponentType; return m; },
    (e: unknown) => { loading = undefined; throw e; },  // a failed preload does not poison the page's own load
  ));
  const Lazy = lazy<React.ComponentType>(() => once().then((m) => ({ default: m[name] as React.ComponentType })));
  // A chunk that is already here renders directly: lazy() would still suspend once, and React throttles a
  // Suspense reveal (~300 ms), which held a preloaded Admin's queries back ~220 ms in the trace.
  function Page(): React.JSX.Element {
    const Loaded = loaded;
    return Loaded ? <Loaded /> : <Lazy />;
  }
  return {
    element: (
      <Suspense fallback={<p className={ui.empty} role="status">Loading…</p>}>
        <Page />
      </Suspense>
    ),
    handle: { preload: once },
  };
}

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
    // t-b2f8859d30: one pathless layout route holds every page, so a page's render error shows PageError in the
    // page's place (inside the shell's Outlet) and the rail keeps working, never the router's full-screen error.
    children: [{ errorElement: <PageError />, children: [
      // S20 (design-e963c656f5 §4.18): the Needs you page is gone; what waits on you is a trail of dots from the
      // Epics list (v34: the rail's Waiting on you entry is gone too). Old /me links land on the Epics list.
      { index: true, element: <RedirectTo to="/epics" /> },
      { path: "me", element: <RedirectTo to="/epics" /> },
      { path: "epics", element: <EpicsPage /> },
      { path: "epic/:id", ...page(() => import("./pages/Epic"), "EpicPage") },
      { path: "ticket/:id", ...page(() => import("./pages/Ticket"), "TicketPage") },
      { path: "doc/:id", ...page(() => import("./pages/Doc"), "DocPage") },
      { path: "records/:id", ...page(() => import("./pages/Records"), "RecordsPage") },
      { path: "artifact/:id", ...page(() => import("./pages/Artifact"), "ArtifactPage") },
      { path: "seats", ...page(() => import("./pages/Seats"), "SeatsPage") },
      { path: "settings", ...page(() => import("./pages/Settings"), "SettingsPage") },
      // S6 (design-e963c656f5 §4.8): the Admin console, admins only (the page says so to anyone else)
      { path: "admin", ...page(() => import("./pages/admin/Admin"), "AdminPage") },
      // S14 (design-e963c656f5 §4.14): the Design tab — every workflow version; admins edit drafts
      { path: "design", ...page(() => import("./pages/design/Design"), "DesignPage") },
      // epic-91fcd3b370 S3: the Code tab (full-bleed; AppShell collapses the rail) and its FAQ
      { path: "code", ...page(() => import("./pages/Code"), "CodePage") },
      { path: "code/faq", ...page(() => import("./pages/Code"), "CodeFaqPage") },
      { path: "library", element: <RedirectTo to="/library/knowledge" /> },
      { path: "library/:section", ...page(() => import("./pages/Library"), "LibraryPage") },
      { path: "library/topics/:id", ...page(() => import("./pages/TopicPage"), "TopicPage") },
      // Legacy paths keep their shape but redirect to Library (preserving ?as=).
      { path: "tickets", element: <RedirectTo to="/library/tickets" /> },
      { path: "activity", element: <RedirectTo to="/library/history" /> },
      { path: "*", element: <NotFoundPage /> },
    ] }],
  },
  // S6: the teammate invite landing and the first-run wizard stand outside the shell (no session yet)
  { path: "/join", ...page(() => import("./pages/admin/Join"), "JoinPage") },
  { path: "/setup", ...page(() => import("./pages/admin/Setup"), "SetupPage") },
];
