import "./app.css";
import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { createBrowserRouter, Navigate, RouterProvider, useLocation } from "react-router";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { ThemeProvider } from "./theme/ThemeProvider";
import { AppShell } from "./components/AppShell";
import {
  DecisionsPage,
  DocPage,
  EpicPage,
  EpicsPage,
  LibraryPage,
  NotFoundPage,
  SeatsPage,
  TicketPage,
} from "./pages";

// Router basename tracks the Vite mount prefix (import.meta.env.BASE_URL, e.g. "/app/"),
// so the later /ui cutover moves the whole SPA by changing one env var — no route edits.
const basename = import.meta.env.BASE_URL.replace(/\/$/, "") || "/";

// Redirects preserve the query string so ?as= survives (parity with the legacy `_qs`).
function RedirectTo({ to }: { to: string }): React.JSX.Element {
  const { search } = useLocation();
  return <Navigate to={`${to}${search}`} replace />;
}

const router = createBrowserRouter(
  [
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
        { path: "seats", element: <SeatsPage /> },
        { path: "library", element: <RedirectTo to="/library/tickets" /> },
        { path: "library/:section", element: <LibraryPage /> },
        // Legacy paths keep their shape but redirect to Library (preserving ?as=).
        { path: "tickets", element: <RedirectTo to="/library/tickets" /> },
        { path: "activity", element: <RedirectTo to="/library/history" /> },
        { path: "*", element: <NotFoundPage /> },
      ],
    },
  ],
  { basename },
);

const queryClient = new QueryClient({
  defaultOptions: { queries: { retry: false, staleTime: 5_000 } },
});

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <QueryClientProvider client={queryClient}>
      <ThemeProvider>
        <RouterProvider router={router} />
      </ThemeProvider>
    </QueryClientProvider>
  </StrictMode>,
);
