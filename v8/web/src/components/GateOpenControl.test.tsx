import { describe, it, expect } from "vitest";
import { screen, waitFor, fireEvent } from "@testing-library/react";
import { server } from "../test/setup";
import { http, okJson, renderRoute } from "../pages/testUtils";
import { GateOpenControl } from "./GateOpenControl";

// Open-a-gate (design §5, §16): posts to /v1/gates/{ticket}/{gate}/open with the chosen kind + note.

describe("GateOpenControl", () => {
  it("opens the chosen gate with its note, then calls onOpened", async () => {
    let path = "";
    let body: unknown = null;
    let opened = false;
    server.use(
      http.post("/v1/gates/s-1/:gate/open", async ({ request, params }) => {
        path = params.gate as string;
        body = await request.json();
        return okJson({ ok: true });
      }),
    );
    renderRoute("/x", "/x", <GateOpenControl ticketId="s-1" onOpened={() => (opened = true)} />);
    fireEvent.change(screen.getByTestId("gate-open-kind"), { target: { value: "demo" } });
    fireEvent.change(screen.getByLabelText("Gate note"), { target: { value: "show the sheet" } });
    fireEvent.click(screen.getByRole("button", { name: /Open the .* gate/ }));
    await waitFor(() => expect(path).toBe("demo"));
    expect(body).toEqual({ note: "show the sheet" });
    expect(opened).toBe(true);
  });

  it("surfaces the board hint when opening is refused", async () => {
    server.use(
      http.post("/v1/gates/s-1/:gate/open", () =>
        new Response(JSON.stringify({ ok: false, hint: "only the owner or architect opens a gate" }), {
          status: 403,
          headers: { "content-type": "application/json" },
        }),
      ),
    );
    renderRoute("/x", "/x", <GateOpenControl ticketId="s-1" />);
    fireEvent.click(screen.getByRole("button", { name: /Open the .* gate/ }));
    expect(await screen.findByTestId("gate-open-error")).toHaveTextContent("only the owner or architect");
  });
});
