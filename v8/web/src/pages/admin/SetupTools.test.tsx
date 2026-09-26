import { describe, it, expect } from "vitest";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { http, HttpResponse } from "msw";
import { server } from "../../test/setup";
import { ThemeProvider } from "../../theme/ThemeProvider";
import { ToolsStep } from "./SetupTools";
import { HarnessSelection } from "./SeatsModels";

// t-08612be1b0: the wizard's "Your tools" checklist (the one prerequisites manifest) and the harness step that
// offers only installed harnesses.

const ok = (value: unknown, hint = "") => HttpResponse.json({ ok: true, value, hint });
const row = (o: Record<string, unknown>) => ({ feature: "", purpose: "p", path: null, version: null, min_version: "", fix: "", installable: true, docs: "https://x", job: null, ...o });

function mount(el: React.ReactNode) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } });
  render(<QueryClientProvider client={qc}><ThemeProvider>{el}</ThemeProvider></QueryClientProvider>);
}

describe("ToolsStep", () => {
  it("shows found, missing with Install, optional off, sign-in, and Docker not needed", async () => {
    let installed: string | null = null;
    let polls = 0;
    server.use(
      http.get("/v1/admin/setup/prereqs", () => {
        polls += 1;
        return ok({
          os: "win32", harness_ok: true, bundled: [{ name: "sqlite", why: "inside Python" }],
          not_needed: [{ name: "docker", why: "not needed: every service runs as a local process" }],
          rows: [
            row({ name: "node", need: "required", state: "ok", version: "v22.1.0" }),
            row({ name: "git", need: "required", state: installed ? "ok" : "missing", version: installed ? "git version 2.47.0" : null, fix: "winget install --id Git.Git --exact",
              job: installed ? { state: "done", exit: 0 } : null }),
            row({ name: "claude", need: "harness", state: "ok", version: "2.0.14", login: "claude   (then type /login)", signed_in: polls > 1 }),
            row({ name: "tailscale", need: "optional", feature: "remote access for teammates", state: "off", fix: "winget install --id Tailscale.Tailscale --exact" }),
            row({ name: "pi", need: "optional", feature: "Pi seats", state: "off", installable: false, docs: "https://pi.example" }),
          ],
        });
      }),
      http.post("/v1/admin/setup/prereqs/:name/install", ({ params }) => { installed = String(params.name); return ok({ state: "running" }); }),
    );
    mount(<ToolsStep onDone={() => undefined} />);
    expect(await screen.findByTestId("prereq-node-state")).toHaveTextContent("Found v22.1.0");
    expect(screen.getByTestId("prereq-git-state")).toHaveTextContent("Missing");
    expect(screen.getByTestId("prereq-git-state")).toHaveTextContent("winget install --id Git.Git --exact");
    expect(screen.getByTestId("setup-tools-missing")).toHaveTextContent("Still missing: git");
    expect(screen.getByTestId("prereq-tailscale-state")).toHaveTextContent("Off: turns on remote access for teammates");
    expect(screen.getByTestId("prereq-tailscale-install")).toBeInTheDocument();
    expect(screen.queryByTestId("prereq-pi-install")).toBeNull();  // no recipe here: the download page instead
    expect(screen.getByTestId("prereq-docker")).toHaveTextContent("not needed");
    // installed but not signed in: the command, then "Signed in" once the poll sees the login
    expect(screen.getByTestId("prereq-claude-login")).toHaveTextContent("claude (then type /login)");
    fireEvent.click(screen.getByTestId("prereq-git-install"));
    await waitFor(() => expect(installed).toBe("git"));
    expect(await screen.findByTestId("prereq-git-state", {}, { timeout: 5000 })).toHaveTextContent("Found git version 2.47.0");
    expect(await screen.findByTestId("prereq-claude-signed-in", {}, { timeout: 5000 })).toHaveTextContent("Signed in");
  });

  it("warns when no harness is installed and shows a failed install's output", async () => {
    server.use(http.get("/v1/admin/setup/prereqs", () => ok({
      os: "linux", harness_ok: false, bundled: [], not_needed: [],
      rows: [row({ name: "claude", need: "harness", state: "missing", fix: "curl -fsSL https://claude.ai/install.sh | sh", job: { state: "failed", exit: 22, output: "curl: (22) 404" } })],
    })));
    mount(<ToolsStep onDone={() => undefined} />);
    expect(await screen.findByTestId("setup-tools-no-harness")).toHaveTextContent("install claude or codex");
    expect(screen.getByTestId("prereq-claude-failed")).toHaveTextContent("exit 22");
  });
});

describe("HarnessSelection installedOnly", () => {
  it("offers only installed harnesses and says how to get the others", async () => {
    server.use(http.get("/v1/admin/harnesses", () => ok({
      harnesses: [{ harness: "claude", selected: true, installed: true, version: "2.0.14", live_seats: [] },
        { harness: "codex", selected: false, installed: false, live_seats: [] },
        { harness: "pi", selected: false, installed: false, live_seats: [] }],
      selected: ["claude"], fable_ack: { by: "owner" }, fable_notice: null,
    })));
    mount(<HarnessSelection installedOnly />);
    await waitFor(() => expect(screen.getByTestId("pick-claude-input")).toBeChecked());
    expect(screen.getByTestId("pick-claude-input")).toBeEnabled();
    expect(screen.getByTestId("pick-codex-input")).toBeDisabled();
    expect(screen.getByTestId("pick-codex-state")).toHaveTextContent("heronry prereqs install --only codex");
  });
});
