import { it, expect } from "vitest";
import { act, renderHook, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { http, HttpResponse } from "msw";
import { server } from "../test/setup";
import { useThreadHistory } from "./useThreadHistory";
import type { MessageView, ThreadPage } from "../api/types";

it("deduplicates pinned messages and reopens the gap after a >100-arrival head change", async () => {
  const rows: MessageView[] = Array.from({ length: 400 }, (_, i) => ({ id: `m-${i + 1}`, seq: i + 1, by: "owner", kind: "note", to: null, reply_to: null, text: String(i + 1), at: "2026-09-18T00:00:00Z" }));
  let total = 235;
  const cursors: number[] = [];
  server.use(http.get("/v1/tickets/epic-history/thread", ({ request }) => {
    const before = Number(new URL(request.url).searchParams.get("before")); cursors.push(before);
    const older = rows.filter((m) => m.seq! < before), window = older.slice(-100);
    return HttpResponse.json({ ok: true, value: { thread: window, thread_total: total, thread_before: older.length > 100 ? window[0].seq : null } });
  }));
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  const wrapper = ({ children }: { children: React.ReactNode }) => <QueryClientProvider client={qc}>{children}</QueryClientProvider>;
  const initial: ThreadPage = { thread: [rows[0], ...rows.slice(135, 235)], thread_total: 235, thread_before: 136 };
  const { result, rerender } = renderHook(({ page }) => useThreadHistory("epic-history", page), { wrapper, initialProps: { page: initial } });
  act(() => result.current.load());
  await waitFor(() => expect(result.current.messages).toHaveLength(201));
  total = 400;
  rerender({ page: { thread: rows.slice(300), thread_total: 400, thread_before: 301 } });
  for (const next of [301, 201, 101]) {
    act(() => result.current.load());
    await waitFor(() => expect(cursors).toContain(next));
    await waitFor(() => expect(result.current.loading).toBe(false));
  }
  expect(cursors).toEqual([136, 301, 201, 101]);
  expect(result.current.messages.map((m) => m.id)).toEqual(rows.map((m) => m.id));
  expect(result.current.total).toBe(400);
  expect(result.current.more).toBe(false);
});
