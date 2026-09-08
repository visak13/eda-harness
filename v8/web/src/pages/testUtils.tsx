import { render } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { HttpResponse, http } from "msw";
import { DocDrawerProvider } from "../components/DocDrawer";

// Shared test harness for the G3a page suites: a fresh QueryClient (retry off, no cache bleed),
// a MemoryRouter at `path`, the DocDrawer provider (pages call useDocDrawer), and a Routes table
// so useParams resolves. A catch-all route lets navigations (e.g. drawer "open ticket") land.
export function renderRoute(
  path: string,
  routePattern: string,
  element: React.JSX.Element,
): { qc: QueryClient } {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(
    <QueryClientProvider client={qc}>
      <MemoryRouter initialEntries={[path]}>
        <DocDrawerProvider>
          <Routes>
            <Route path={routePattern} element={element} />
            <Route path="*" element={<div data-testid="elsewhere" />} />
          </Routes>
        </DocDrawerProvider>
      </MemoryRouter>
    </QueryClientProvider>,
  );
  return { qc };
}

/** `{ok,value,hint}` envelope — the exact shape the board returns (strategy_ll §5). */
export const okJson = (value: unknown, hint = "") => HttpResponse.json({ ok: true, value, hint });

/** Register a GET handler returning the envelope for `value`. */
export const getOk = (path: string, value: unknown, hint = "") =>
  http.get(path, () => okJson(value, hint));

export { http, HttpResponse };
