import { describe, it, expect } from "vitest";
import { server } from "../test/setup";
import { http, okJson } from "../pages/testUtils";
import { getDoc, getDocSource } from "./endpoints";

// S17 (ruling m-639da0243d): GET /v1/docs/{id} returns the head by default, so every web caller that needs the
// whole body asks for all=true: the Library editor (KnowledgeDetail → getDoc) and the quote check (QuoteLayer →
// getDocSource).
function capture(): { urls: string[] } {
  const seen = { urls: [] as string[] };
  server.use(http.get("/v1/docs/:id", ({ request }) => {
    seen.urls.push(request.url);
    return okJson({ id: "note-1", title: "t", body_md: "whole", version: 3 });
  }));
  return seen;
}

describe("doc GET callers ask for the whole body", () => {
  it("the Library editor's getDoc passes all=true", async () => {
    const seen = capture();
    expect((await getDoc("note-1")).body_md).toBe("whole");
    expect(new URL(seen.urls[0]).searchParams.get("all")).toBe("true");
  });

  it("the quote layer's getDocSource passes the version and all=true", async () => {
    const seen = capture();
    await getDocSource("note-1", 3);
    const q = new URL(seen.urls[0]).searchParams;
    expect([q.get("version"), q.get("all")]).toEqual(["3", "true"]);
  });
});
