import { describe, it, expect, vi, afterEach } from "vitest";
import { http, HttpResponse } from "msw";
import { server } from "../test/setup";
import { dispositionOf, openArtifact } from "./ArtifactLink";

// Adversary round 2 #1 (2026-09-10): an artifact the board serves as `attachment` (an SVG above
// all — it can script at top level from a same-origin blob: URL) is SAVED through <a download>,
// never navigated to; only the inline image allowlist previews in a new tab; a blocked popup
// never falls back to navigating the SPA's own tab.
describe("openArtifact honours Content-Disposition", () => {
  afterEach(() => vi.restoreAllMocks());

  it("dispositionOf: inline only for the safe image types", () => {
    const h = (cd: string, ct: string) => ({ headers: { get: (n: string) => (n === "content-disposition" ? cd : ct) } });
    expect(dispositionOf(h('inline; filename="a.png"', "image/png"))).toEqual({ inline: true, filename: "a.png" });
    expect(dispositionOf(h('attachment; filename="a.svg"', "image/svg+xml")).inline).toBe(false);
    expect(dispositionOf(h('inline; filename="a.svg"', "image/svg+xml")).inline).toBe(false); // type wins
    expect(dispositionOf(h("", "image/png")).inline).toBe(false); // no header → download
  });

  it("an attachment SVG is downloaded, not opened, and the current tab is never navigated", async () => {
    server.use(
      http.get("/v1/artifacts/art-abc123/content", () =>
        new HttpResponse("<svg xmlns='http://www.w3.org/2000/svg'><script>1</script></svg>", {
          headers: { "content-type": "image/svg+xml", "content-disposition": 'attachment; filename="evil.svg"' },
        }),
      ),
    );
    const open = vi.spyOn(window, "open").mockReturnValue(null);
    const create = vi.spyOn(URL, "createObjectURL").mockReturnValue("blob:x/1");
    vi.spyOn(URL, "revokeObjectURL").mockImplementation(() => {});
    const clicks: HTMLAnchorElement[] = [];
    vi.spyOn(HTMLAnchorElement.prototype, "click").mockImplementation(function (this: HTMLAnchorElement) {
      clicks.push(this);
    });
    const before = window.location.href;
    await openArtifact("art-abc123");
    expect(open).not.toHaveBeenCalled();
    expect(create).toHaveBeenCalledTimes(1);
    expect(clicks).toHaveLength(1);
    expect(clicks[0].download).toBe("evil.svg");
    expect(clicks[0].href).toBe("blob:x/1");
    expect(window.location.href).toBe(before);
  });

  it("an inline PNG opens in a new tab; a blocked popup degrades to a download", async () => {
    server.use(
      http.get("/v1/artifacts/art-def456/content", () =>
        new HttpResponse(new Uint8Array([137, 80, 78, 71]), {
          headers: { "content-type": "image/png", "content-disposition": 'inline; filename="shot.png"' },
        }),
      ),
    );
    vi.spyOn(URL, "createObjectURL").mockReturnValue("blob:x/2");
    vi.spyOn(URL, "revokeObjectURL").mockImplementation(() => {});
    const clicks: HTMLAnchorElement[] = [];
    vi.spyOn(HTMLAnchorElement.prototype, "click").mockImplementation(function (this: HTMLAnchorElement) {
      clicks.push(this);
    });
    const open = vi.spyOn(window, "open").mockReturnValue({} as Window);
    await openArtifact("art-def456");
    expect(open).toHaveBeenCalledWith("blob:x/2", "_blank", "noopener");
    expect(clicks).toHaveLength(0);

    open.mockReturnValue(null); // popup blocked
    await openArtifact("art-def456");
    expect(clicks).toHaveLength(1);
    expect(clicks[0].download).toBe("shot.png");
  });
});

describe("ArtifactLink copy link (promise #20)", () => {
  it("renders a Copy link next to the artifact that yields the shareable /ui/artifact/<id> URL", async () => {
    vi.stubEnv("BASE_URL", "/ui/"); // vitest serves at "/"; the built SPA mounts at /ui/
    const writeText = vi.fn(() => Promise.resolve());
    Object.defineProperty(navigator, "clipboard", { value: { writeText }, configurable: true });
    const { render, screen, fireEvent, waitFor } = await import("@testing-library/react");
    const { MessageText } = await import("./ArtifactLink");
    render(<MessageText text="see art-abc123 for the shot" />);
    const copy = screen.getByTestId("artifact-copy-link");
    expect(copy).toHaveAttribute("data-artifact", "art-abc123");
    fireEvent.click(copy);
    await waitFor(() => expect(writeText).toHaveBeenCalledWith(`${window.location.origin}/ui/artifact/art-abc123`));
    expect(copy).toHaveTextContent("Link copied");
  });
});
