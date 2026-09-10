import "./app.css";
import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { createBrowserRouter, RouterProvider } from "react-router";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { ThemeProvider } from "./theme/ThemeProvider";
import { appRoutes } from "./routes";

// Router basename tracks the Vite mount prefix (import.meta.env.BASE_URL, e.g. "/ui/"),
// so the later /ui cutover moves the whole SPA by changing one env var — no route edits.
const basename = import.meta.env.BASE_URL.replace(/\/$/, "") || "/";

// The route table lives in src/routes.tsx so the dead-control lint (human #26) walks the same objects.
const router = createBrowserRouter(appRoutes, { basename });

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
