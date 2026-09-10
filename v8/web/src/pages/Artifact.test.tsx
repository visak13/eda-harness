import { describe, it, expect, vi, afterEach } from "vitest";
import { screen, fireEvent, waitFor } from "@testing-library/react";
import { HttpResponse } from "msw";
import { server } from "../test/setup";
import { http, okJson, renderRoute } from "./testUtils";
import { ArtifactPage } from "./Artifact";
import { artifactShareUrl } from "../components/ArtifactLink";

// Promise #20: a shareable /ui/artifact/:id page.
const record = (over: Record<string, unknown> = {}) => ({
  id: "art-abc123",
  form: "image",
  uri: "file:///x/shot.png",
  note: "the seat rail at 1024",
  created_by: "engineer.s-1",
  created_at: "2026-09-10T10:00:00Z",
  content_type: "image/png",
  filename: "shot.png",
  ...over,
});

function clipboard() {
  vi.stubEnv("BASE_URL", "/ui/"); // vitest serves at "/"; the built SPA mounts at /ui/ (vite.config base)
  const writeText = vi.fn(() => Promise.resolve());
  Object.defineProperty(navigator, "clipboard", { value: { writeText }, configurable: true });
  return writeText;
}

describe("ArtifactPage", () => {
  afterEach(() => {
    vi.restoreAllMocks();
    vi.unstubAllEnvs();
  });

  it("previews an inline PNG through an authenticated fetch and shows note / uploader / form", async () => {
    server.use(
      http.get("/v1/artifacts/art-abc123", () => okJson(record())),
      http.get("/v1/artifacts/art-abc123/content", ({ request }) => {
        expect(request.headers.get("x-participant")).toBeTruthy(); // never a bare <img src>
        return new HttpResponse(new Uint8Array([137, 80, 78, 71]), {
          headers: { "content-type": "image/png", "content-disposition": 'inline; filename="shot.png"' },
        });
      }),
    );
    vi.spyOn(URL, "createObjectURL").mockReturnValue("blob:x/1");
    vi.spyOn(URL, "revokeObjectURL").mockImplementation(() => {});
    renderRoute("/artifact/art-abc123?as=owner", "/artifact/:id", <ArtifactPage />);
    const img = await screen.findByTestId("artifact-preview");
    expect(img).toHaveAttribute("src", "blob:x/1");
    expect(screen.getByTestId("artifact-note")).toHaveTextContent("the seat rail at 1024");
    expect(screen.getByTestId("artifact-by")).toHaveTextContent("engineer.s-1");
    expect(screen.getByTestId("artifact-form")).toHaveTextContent("image");
    expect(screen.queryByTestId("artifact-download")).toBeNull();
  });

  it("offers Download (never an inline render) for a non-image artifact", async () => {
    server.use(
      http.get("/v1/artifacts/art-abc123", () =>
        okJson(record({ form: "file", content_type: "image/svg+xml", filename: "evil.svg" })),
      ),
      http.get("/v1/artifacts/art-abc123/content", () =>
        new HttpResponse("<svg xmlns='http://www.w3.org/2000/svg'/>", {
          headers: { "content-type": "image/svg+xml", "content-disposition": 'attachment; filename="evil.svg"' },
        }),
      ),
    );
    vi.spyOn(URL, "createObjectURL").mockReturnValue("blob:x/2");
    vi.spyOn(URL, "revokeObjectURL").mockImplementation(() => {});
    const clicks: HTMLAnchorElement[] = [];
    vi.spyOn(HTMLAnchorElement.prototype, "click").mockImplementation(function (this: HTMLAnchorElement) {
      clicks.push(this);
    });
    renderRoute("/artifact/art-abc123", "/artifact/:id", <ArtifactPage />);
    const dl = await screen.findByTestId("artifact-download");
    expect(screen.queryByTestId("artifact-preview")).toBeNull();
    fireEvent.click(dl);
    await waitFor(() => expect(clicks).toHaveLength(1));
    expect(clicks[0].download).toBe("evil.svg");
  });

  it("Copy link puts ${origin}/ui/artifact/<id> on the clipboard and says so", async () => {
    server.use(http.get("/v1/artifacts/art-abc123", () => okJson(record({ content_type: "text/plain", form: "file" }))));
    const writeText = clipboard();
    renderRoute("/artifact/art-abc123", "/artifact/:id", <ArtifactPage />);
    fireEvent.click(await screen.findByTestId("artifact-copy-link"));
    await waitFor(() => expect(writeText).toHaveBeenCalledWith(`${window.location.origin}/ui/artifact/art-abc123`));
    expect(await screen.findByText("Link copied")).toBeInTheDocument();
    expect(artifactShareUrl("art-abc123")).toMatch(/\/ui\/artifact\/art-abc123$/);
  });

  it("shows the board's hint verbatim when the artifact is unknown", async () => {
    server.use(
      http.get("/v1/artifacts/art-nope", () =>
        HttpResponse.json({ ok: false, error: "'art-nope' is not an artifact", hint: "no such artifact" }, { status: 404 }),
      ),
    );
    renderRoute("/artifact/art-nope", "/artifact/:id", <ArtifactPage />);
    expect(await screen.findByTestId("artifact-error")).toHaveTextContent("no such artifact");
  });
});
