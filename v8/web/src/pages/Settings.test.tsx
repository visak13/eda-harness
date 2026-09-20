import { describe, it, expect } from "vitest";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { MemoryRouter } from "react-router";
import { http, HttpResponse } from "msw";
import { server } from "../test/setup";
import { ThemeProvider } from "../theme/ThemeProvider";
import type { UserSettings } from "../api/types";
import { SettingsPage } from "./Settings";

// s-7f663c6322: the Settings page launched from the account menu — Profile / Notifications / Slack
// tabs, persisted through GET/PUT /v1/me/settings, webhook masked on read, honest about sign-in.

const stored: UserSettings = {
  profile: { display_name: "Vishal", timezone: "Asia/Kolkata" },
  notifications: { browser: true, quiet: null },
  slack: { enabled: true, slack_id: "U0123456789", webhook_url: "https://hooks.slack.com/services/••••", webhook_set: true, quiet: [22, 7] },
};

function mount(tab = "profile", handlers: Parameters<typeof server.use> = []) {
  server.use(
    ...handlers, // first match wins: a test's override precedes the defaults
    http.get("/v1/me/avatar", () => HttpResponse.json({ ok: true, value: { kind: "seed", seed: "v", url: null, choices: [] } })),
    http.get("/v1/me/settings", () => HttpResponse.json({ ok: true, value: stored })),
  );
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={qc}>
      <ThemeProvider>
        <MemoryRouter initialEntries={[`/settings?tab=${tab}`]}>
          <SettingsPage />
        </MemoryRouter>
      </ThemeProvider>
    </QueryClientProvider>,
  );
}

describe("SettingsPage", () => {
  it("shows the three tabs, loads the stored profile and says sign-in is not available", async () => {
    mount();
    expect(screen.getByRole("tab", { name: "Profile" })).toBeInTheDocument();
    expect(screen.getByRole("tab", { name: "Notifications" })).toBeInTheDocument();
    expect(screen.getByRole("tab", { name: "Slack" })).toBeInTheDocument();
    await waitFor(() => expect(screen.getByTestId("settings-display-name")).toHaveValue("Vishal"));
    expect(screen.getByTestId("settings-signin")).toHaveTextContent(/Not available yet/);
    expect(screen.getByTestId("settings-signin")).toHaveTextContent(/OAuth app the owner provisions/);
    expect(screen.getByTestId("settings-save")).toBeDisabled();
  });

  it("switches to the Slack tab, shows the masked webhook and quiet hours", async () => {
    mount("slack");
    await waitFor(() => expect(screen.getByTestId("settings-slack-enabled")).toBeChecked());
    expect(screen.getByTestId("settings-slack-id")).toHaveValue("U0123456789");
    expect(screen.getByTestId("settings-slack")).toHaveTextContent(/shown masked/);
    expect(screen.getByTestId("slack-quiet")).toBeChecked();
    expect(screen.getByLabelText("Quiet from (hour)")).toHaveValue(22);
  });

  it("PUTs the edited settings and reports the bridge hint", async () => {
    let sent: UserSettings | null = null;
    mount("slack", [
      http.put("/v1/me/settings", async ({ request }) => {
        sent = (await request.json()) as UserSettings;
        return HttpResponse.json({ ok: true, value: { ...sent, slack: { ...sent.slack, webhook_url: "", webhook_set: true } }, hint: "saved; the Slack bridge picks the change up within a minute" });
      }),
    ]);
    await waitFor(() => expect(screen.getByTestId("settings-slack-id")).toHaveValue("U0123456789"));
    fireEvent.change(screen.getByTestId("settings-slack-id"), { target: { value: "U0000000001" } });
    expect(screen.getByTestId("settings-save")).toBeEnabled();
    fireEvent.click(screen.getByTestId("settings-save"));
    await waitFor(() => expect(screen.getByTestId("settings-saved")).toHaveTextContent(/within a minute/));
    expect(sent!.slack.slack_id).toBe("U0000000001");
    expect(sent!.slack.enabled).toBe(true);
    expect(screen.getByTestId("settings-save")).toBeDisabled();
  });

  it("tells an agent seat that settings belong to people", async () => {
    mount("profile", [http.get("/v1/me/settings", () => HttpResponse.json({ ok: false, error: { code: "forbidden", message: "settings belong to people" }, hint: "" }, { status: 403 }))]);
    await waitFor(() => expect(screen.getByTestId("settings-forbidden")).toBeInTheDocument());
    expect(screen.getByTestId("settings-save")).toBeDisabled();
  });
});
