import { describe, it, expect, beforeEach, vi } from "vitest";
import { render, screen, fireEvent, waitFor, within } from "@testing-library/react";
import { MemoryRouter, Routes, Route } from "react-router";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { http, HttpResponse } from "msw";
import { server } from "../test/setup";
import { ThemeProvider } from "../theme/ThemeProvider";
import { renderRoute, okJson } from "../pages/testUtils";
import { displayHandle, hideFromGuests } from "../auth/guest";
import { AppShell } from "./AppShell";
import { StatusControl } from "./StatusControl";
import { GateOpenControl } from "./GateOpenControl";
import { AssignControl } from "./AssignControl";
import { AddCriterion } from "./CriterionControls";
import { DocControls } from "./DocControls";
import { CriterionCard } from "./CriterionCard";
import { EpicPeople } from "./EpicPeople";
import type { CriterionView } from "../api/types";

// e0cec S5 (design-b6a55eed13 §4.B, c-cefaeb51a3): a guest's UI names it ext:<handle> and hides every control the
// board refuses it (gates, verdicts, spawn, status, admin, models, Code); the owner manages an epic's guests in People.

const GUEST = { participant: { id: "gina", handle: "gina", role: "guest", type: "human" }, tickets: [], admin: false };
const OWNER = { participant: { id: "owner", handle: "owner", role: "owner", type: "human" }, tickets: [], admin: true };
const whoami = (who: unknown) => http.get("/v1/whoami", () => okJson(who));

beforeEach(() => {
  vi.stubGlobal("ResizeObserver", class { observe() {} disconnect() {} });
  server.use(http.get("/v1/me/avatar", () => HttpResponse.json({ ok: true, value: { catalog: [] } })));
  localStorage.clear();
});

describe("guest identity", () => {
  it("a guest is always ext:<handle>; anyone else keeps the plain handle", () => {
    expect(displayHandle({ handle: "gina", role: "guest" })).toBe("ext:gina");
    expect(displayHandle({ handle: "@gina", role: "guest" })).toBe("ext:gina");
    expect(displayHandle({ handle: "olive", role: "owner" })).toBe("olive");
  });

  it("hideFromGuests renders the control for a teammate and nothing for a guest", async () => {
    const Probe = hideFromGuests(() => <button type="button">decide</button>);
    server.use(whoami(OWNER));
    const a = renderRoute("/x", "/x", <Probe />);
    expect(await screen.findByRole("button", { name: "decide" })).toBeInTheDocument();
    a.qc.clear();
  });
});

function shell(initial = "/epics") {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={qc}>
      <ThemeProvider>
        <MemoryRouter initialEntries={[initial]}>
          <Routes>
            <Route element={<AppShell />}>
              <Route path="epics" element={<div>epics body</div>} />
            </Route>
          </Routes>
        </MemoryRouter>
      </ThemeProvider>
    </QueryClientProvider>,
  );
}

describe("guest shell", () => {
  it("the rail keeps only Epics (no Seats, Library, Code, Design, Admin or Ask for help) and names the guest ext:<handle>", async () => {
    server.use(whoami(GUEST));
    shell();
    await waitFor(() => expect(screen.getByTestId("whoami-handle")).toHaveTextContent("ext:gina"));
    expect(screen.getByTestId("identity")).toHaveTextContent("ext:gina");
    const nav = screen.getByRole("navigation", { name: "Sections" });
    expect(within(nav).getAllByRole("link").map((l) => l.textContent?.replace(/\d+$/, "").trim())).toEqual(["Epics"]);
    expect(screen.queryByTestId("nav-admin")).toBeNull();
    expect(screen.queryByTestId("ask-help")).toBeNull();
  });

  it("a teammate's rail is unchanged", async () => {
    server.use(whoami(OWNER));
    shell();
    expect(await screen.findByTestId("nav-admin")).toBeInTheDocument();
    const nav = screen.getByRole("navigation", { name: "Sections" });
    expect(within(nav).getByRole("link", { name: /^Code/ })).toBeInTheDocument();
  });
});

describe("guest controls", () => {
  const controls: [string, React.JSX.Element][] = [
    ["status", <StatusControl key="s" ticketId="s-1" currentStatus="in_progress" />],
    ["raise a gate", <GateOpenControl key="g" ticketId="s-1" />],
    ["assign", <AssignControl key="a" ticketId="s-1" currentAssignee={null} />],
    ["add criterion", <AddCriterion key="c" ticketId="s-1" />],
    ["doc controls", <DocControls key="d" docId="d1" scope="epic-1" version={1} scopeIsThread />],
  ];
  for (const [name, el] of controls) {
    it(`${name}: shown to a teammate, hidden from a guest`, async () => {
      server.use(whoami(OWNER));
      const { unmount } = render(<QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>
        <MemoryRouter><div data-testid="host">{el}</div></MemoryRouter></QueryClientProvider>);
      await waitFor(() => expect(screen.getByTestId("host")).not.toBeEmptyDOMElement());
      unmount();
      server.use(whoami(GUEST));
      const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
      render(<QueryClientProvider client={qc}><MemoryRouter><div data-testid="host">{el}</div></MemoryRouter></QueryClientProvider>);
      await waitFor(() => expect(qc.getQueryData(["whoami"])).toBeTruthy());
      expect(screen.getByTestId("host")).toBeEmptyDOMElement();
    });
  }

  it("the criterion card shows a guest the criterion but never the verdict pane", async () => {
    const crit: CriterionView = { id: "c-abc", text: "It works.", check: "verdict", checked_by: "owner", verdict: "pending",
      evidence_ref: "report-1", evidence_version: 2 };
    server.use(whoami(GUEST));
    const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    render(<QueryClientProvider client={qc}><CriterionCard criterion={crit} ruling={{ evidenceVersion: 2 }} ticketId="s-1" /></QueryClientProvider>);
    await waitFor(() => expect(qc.getQueryData(["whoami"])).toBeTruthy());
    expect(screen.getByText("It works.")).toBeInTheDocument();
    expect(screen.queryByTestId("approve")).toBeNull();
    expect(screen.queryByTestId("needs-work")).toBeNull();
  });
});

describe("epic People panel", () => {
  const row = { id: "gina", handle: "gina", display: "ext:gina", role: "guest", type: "human" };

  it("the owner sees the guests, adds one and removes one (PUT carries the full list)", async () => {
    const puts: unknown[] = [];
    let members = [row];
    server.use(
      whoami(OWNER),
      http.get("/v1/epics/epic-1/members", () => okJson({ epic_id: "epic-1", members })),
      http.get("/v1/participants", ({ request }) => {
        expect(new URL(request.url).searchParams.get("role")).toBe("guest");
        return okJson([{ id: "gina", handle: "gina", role: "guest", type: "human" }, { id: "hal", handle: "hal", role: "guest", type: "human" }]);
      }),
      http.put("/v1/epics/epic-1/members", async ({ request }) => {
        const body = (await request.json()) as { members: string[] };
        puts.push(body);
        members = body.members.map((id) => ({ ...row, id, handle: id, display: `ext:${id}` }));
        return okJson({ epic_id: "epic-1", members });
      }),
    );
    renderRoute("/x", "/x", <EpicPeople epicId="epic-1" />);
    const listed = () => screen.queryAllByTestId("people-row").map((r) => r.getAttribute("data-member"));
    await waitFor(() => expect(listed()).toEqual(["gina"]));
    expect(screen.getByTestId("people-row")).toHaveTextContent("ext:gina");
    await waitFor(() => expect(screen.getByRole("option", { name: "ext:hal" })).toBeInTheDocument());
    expect(screen.queryByRole("option", { name: "ext:gina" })).toBeNull(); // already a member
    fireEvent.change(screen.getByTestId("people-pick"), { target: { value: "hal" } });
    fireEvent.click(screen.getByTestId("people-add"));
    await waitFor(() => expect(listed()).toEqual(["gina", "hal"]));
    expect(puts[0]).toEqual({ members: ["gina", "hal"] });
    fireEvent.click(screen.getByRole("button", { name: "Remove ext:gina" }));
    await waitFor(() => expect(listed()).toEqual(["hal"]));
    expect(puts[1]).toEqual({ members: ["hal"] });
  });

  it("a guest reads the list but has no add or remove", async () => {
    server.use(whoami(GUEST), http.get("/v1/epics/epic-1/members", () => okJson({ epic_id: "epic-1", members: [row] })));
    const { qc } = renderRoute("/x", "/x", <EpicPeople epicId="epic-1" />);
    expect(await screen.findByText("ext:gina")).toBeInTheDocument();
    await waitFor(() => expect(qc.getQueryData(["whoami"])).toBeTruthy());
    expect(screen.queryByTestId("people-add")).toBeNull();
    expect(screen.queryByTestId("people-remove")).toBeNull();
  });

  it("an empty epic says it has no guests", async () => {
    server.use(whoami(OWNER), http.get("/v1/epics/epic-1/members", () => okJson({ epic_id: "epic-1", members: [] })),
      http.get("/v1/participants", () => okJson([])));
    renderRoute("/x", "/x", <EpicPeople epicId="epic-1" />);
    expect(await screen.findByTestId("people-empty")).toHaveTextContent("No guests on this epic.");
  });
});
