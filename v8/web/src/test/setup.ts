import "@testing-library/jest-dom/vitest";
import { afterAll, afterEach, beforeAll } from "vitest";
import { setupServer } from "msw/node";
import { handlers } from "./handlers";

// One msw server for the whole unit suite. `onUnhandledRequest: "error"` makes a request to
// an unmocked path fail loudly rather than hit the network (strategy_ll §5).
export const server = setupServer(...handlers);

beforeAll(() => server.listen({ onUnhandledRequest: "error" }));
afterEach(() => {
  server.resetHandlers();
  Object.keys(sessionStorage).filter((key) => key.startsWith("edp8.draft.")).forEach((key) => sessionStorage.removeItem(key));
});
afterAll(() => server.close());

// jsdom has no matchMedia. Provide a stub that reports no preference by default; the OS
// media-default ORDER is proven directly against resolveTheme(match) and end-to-end in
// Playwright (which emulates the real queries).
if (typeof window !== "undefined" && !window.matchMedia) {
  window.matchMedia = (query: string) =>
    ({
      matches: false,
      media: query,
      onchange: null,
      addListener: () => {},
      removeListener: () => {},
      addEventListener: () => {},
      removeEventListener: () => {},
      dispatchEvent: () => false,
    }) as unknown as MediaQueryList;
}

// jsdom has no ResizeObserver; AnchoredPanel (usage, account, actions menus) observes its anchor.
if (typeof window !== "undefined" && !("ResizeObserver" in window)) {
  (window as unknown as { ResizeObserver: unknown }).ResizeObserver = class { observe() {} unobserve() {} disconnect() {} };
}
