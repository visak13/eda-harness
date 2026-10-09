import { afterEach, describe, expect, it } from "vitest";
import { render, screen } from "@testing-library/react";
import { IdentityPanel } from "./IdentityPanel";

// qa report-689ceb50f0 fail 12: a first visit sends no credentials, so the board cannot have "rejected" them.
describe("IdentityPanel", () => {
  afterEach(() => { try { sessionStorage.removeItem("edp8.token"); } catch { /* none */ } });

  it("a first visit with no token says to sign in, and does not claim a rejection", () => {
    render(<IdentityPanel />);
    expect(screen.getByTestId("identity-panel")).toHaveTextContent("Sign in to use this board.");
    expect(screen.getByTestId("identity-panel")).not.toHaveTextContent(/reject/i);
  });

  // qa 0.10.8: a public board showed the owner's handle to strangers in a pre-filled Participant box.
  it("starts with Participant empty, never the default \"owner\"", () => {
    render(<IdentityPanel />);
    expect(screen.getByTestId("identity-as")).toHaveValue("");
  });

  // architect m-67dc851e4f: no red banner on an untouched card; after an attempt it names the cause.
  it("shows no error until a sign-in attempt, then says the participant and token do not match", () => {
    const { unmount } = render(<IdentityPanel />);
    expect(screen.queryByTestId("identity-hint")).not.toBeInTheDocument();
    unmount();
    sessionStorage.setItem("edp8.sign-in-tried", "1");
    try {
      render(<IdentityPanel />);
      expect(screen.getByTestId("identity-hint")).toHaveTextContent("That participant and token don't match.");
    } finally { sessionStorage.removeItem("edp8.sign-in-tried"); }
  });

  it("offers back only what this browser itself used before", () => {
    localStorage.setItem("edp8.last-participant", "maria");
    try {
      render(<IdentityPanel />);
      expect(screen.getByTestId("identity-as")).toHaveValue("maria");
    } finally { localStorage.removeItem("edp8.last-participant"); }
  });
});
