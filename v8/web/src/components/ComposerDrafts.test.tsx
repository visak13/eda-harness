import { useState } from "react";
import { describe, it, expect } from "vitest";
import { fireEvent, screen } from "@testing-library/react";
import { http, HttpResponse } from "msw";
import { server } from "../test/setup";
import { renderRoute } from "../pages/testUtils";
import { Composer } from "./Composer";
function Harness() {
  const [reply, setReply] = useState(false);
  const [shown, setShown] = useState(true);
  return <><button onClick={() => setReply((v) => !v)}>Toggle reply</button><button onClick={() => setShown((v) => !v)}>Toggle view</button>
    {shown ? <Composer ticketId="epic-draft" replyTo={reply ? "m-reply" : null} to={reply ? "architect" : null} kinds={reply ? ["answer", "note"] : ["note", "question"]} showTo /> : null}</>;
}
describe("draft identity and delivery semantics", () => {
  it("source and reply drafts do not overwrite each other; kind and recipient survive remount", async () => {
    server.use(http.get("/v1/me/people", () => HttpResponse.json({ ok: true, value: [] })), http.post("/v1/messages/resolve", () => HttpResponse.json({ ok: true, value: { plan: [], note: "Saved" } })));
    renderRoute("/x", "/x", <Harness />);
    fireEvent.change(screen.getByRole("textbox", { name: "Message" }), { target: { value: "Original unsent question" } });
    fireEvent.change(screen.getByLabelText("Message kind"), { target: { value: "question" } });
    fireEvent.change(screen.getByLabelText("Recipient"), { target: { value: "engineer" } });
    fireEvent.click(screen.getByText("Toggle reply"));
    expect(screen.getByRole("textbox", { name: "Message" })).toHaveValue("");
    fireEvent.change(screen.getByRole("textbox", { name: "Message" }), { target: { value: "Separate reply" } });
    fireEvent.click(screen.getByText("Toggle reply"));
    expect(screen.getByRole("textbox", { name: "Message" })).toHaveValue("Original unsent question");
    expect(screen.getByLabelText("Message kind")).toHaveValue("question");
    expect(screen.getByLabelText("Recipient")).toHaveValue("engineer");
    fireEvent.click(screen.getByText("Toggle view")); fireEvent.click(screen.getByText("Toggle view"));
    expect(screen.getByLabelText("Message kind")).toHaveValue("question");
    expect(screen.getByLabelText("Recipient")).toHaveValue("engineer");
    fireEvent.click(screen.getByText("Toggle reply"));
    expect(screen.getByRole("textbox", { name: "Message" })).toHaveValue("Separate reply");
  });
});
