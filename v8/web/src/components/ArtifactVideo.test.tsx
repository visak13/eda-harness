import { describe, it, expect, vi, afterEach } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { http, HttpResponse } from "msw";
import { server } from "../test/setup";
import { ArtifactLink, ArtifactVideo, dispositionOf, isVideoType } from "./ArtifactLink";
import { deferArtifactMedia, Markdown } from "./Markdown";

// t-f01372d361: the board plays video. mp4/webm artifacts are served inline; the SPA plays them in
// a <video controls preload="metadata"> fed by the AUTHENTICATED fetch (a bare src would 401), in
// thread attachments, on gate cards (art- tokens → ArtifactLink) and in doc markdown.
const MP4 = new Uint8Array([0, 0, 0, 32, 102, 116, 121, 112, 105, 115, 111, 109]);

function video(id: string, auth: { seen: string | null }) {
  return http.get(`/v1/artifacts/${id}/content`, ({ request }) => {
    auth.seen = request.headers.get("x-participant");
    return new HttpResponse(MP4, { headers: { "content-type": "video/mp4", "content-disposition": 'inline; filename="demo.mp4"' } });
  });
}

function wrap(ui: React.ReactNode) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(<QueryClientProvider client={qc}><MemoryRouter>{ui}</MemoryRouter></QueryClientProvider>);
}

describe("board video (t-f01372d361)", () => {
  afterEach(() => vi.restoreAllMocks());

  it("video types are inline; the served type still decides", () => {
    const h = (cd: string, ct: string) => ({ headers: { get: (n: string) => (n === "content-disposition" ? cd : ct) } });
    expect(isVideoType("video/mp4")).toBe(true);
    expect(isVideoType("video/webm; codecs=vp9")).toBe(true);
    expect(isVideoType("video/quicktime")).toBe(false);
    expect(dispositionOf(h('inline; filename="d.mp4"', "video/mp4")).inline).toBe(true);
    expect(dispositionOf(h('attachment; filename="d.mp4"', "video/mp4")).inline).toBe(false);
  });

  it("ArtifactVideo plays the authenticated blob with controls and metadata preload", async () => {
    const auth = { seen: null as string | null };
    server.use(video("art-aaa111", auth));
    vi.spyOn(URL, "createObjectURL").mockReturnValue("blob:x/v1");
    vi.spyOn(URL, "revokeObjectURL").mockImplementation(() => {});
    wrap(<ArtifactVideo id="art-aaa111" label="demo cut" />);
    const v = (await screen.findByTestId("artifact-video")) as HTMLVideoElement;
    expect(v.tagName).toBe("VIDEO");
    expect(v.getAttribute("src")).toBe("blob:x/v1");
    expect(v.controls).toBe(true);
    expect(v.getAttribute("preload")).toBe("metadata");
    expect(auth.seen).not.toBeNull(); // sent with the viewer's identity headers
  });

  it("a gate card's art- token renders the video in place", async () => {
    server.use(
      http.get("/v1/artifacts/art-bbb222", () => HttpResponse.json({ ok: true, value: {
        id: "art-bbb222", form: "file", content_type: "video/mp4", note: "final cut", has_content: true, uri: "", created_by: "e" } })),
      video("art-bbb222", { seen: null }),
    );
    vi.spyOn(URL, "createObjectURL").mockReturnValue("blob:x/v2");
    vi.spyOn(URL, "revokeObjectURL").mockImplementation(() => {});
    wrap(<ArtifactLink id="art-bbb222" />);
    const v = await screen.findByTestId("artifact-video");
    expect(v.getAttribute("src")).toBe("blob:x/v2");
  });

  it("doc markdown: an artifact <img> is parked (no unauthenticated request) and hydrated", async () => {
    const parked = deferArtifactMedia('<p><img alt="cut" src="/v1/artifacts/art-ccc333/content"><img src="https://example.com/a.png"></p>');
    expect(parked).toContain('data-artifact-src="art-ccc333"');
    expect(parked).not.toContain("/v1/artifacts/art-ccc333/content");
    expect(parked).toContain('src="https://example.com/a.png"'); // other images untouched

    server.use(
      video("art-ccc333", { seen: null }),
      http.get("/v1/artifacts/art-ddd444/content", () =>
        new HttpResponse(new Uint8Array([137, 80, 78, 71]), { headers: { "content-type": "image/png", "content-disposition": "inline" } })),
    );
    let n = 0;
    vi.spyOn(URL, "createObjectURL").mockImplementation(() => `blob:x/m${++n}`);
    vi.spyOn(URL, "revokeObjectURL").mockImplementation(() => {});
    const { container } = wrap(<Markdown html={'<p><img alt="cut" src="/v1/artifacts/art-ccc333/content"> <img alt="shot" src="/v1/artifacts/art-ddd444/content"></p>'} />);
    const v = (await screen.findByTestId("artifact-video")) as HTMLVideoElement;
    expect(v.controls).toBe(true);
    expect(v.getAttribute("preload")).toBe("metadata");
    expect(v.getAttribute("aria-label")).toBe("cut");
    await waitFor(() => expect(container.querySelector('img[alt="shot"]')?.getAttribute("src")).toMatch(/^blob:x\/m/));
  });
});
