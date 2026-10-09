import { describe, it, expect } from "vitest";
import { screen, fireEvent } from "@testing-library/react";
import { renderRoute } from "../pages/testUtils";
import { ActionsMenu, dialogTitle, sentence } from "./ActionsMenu";

// S12-ui (owner m-839aa76c90): the menu label "Models…" leaked its ellipsis into the dialog's title, and the gloss
// opened the dialog in lower case.
describe("ActionsMenu drawer", () => {
  it("titles the dialog without the menu's ellipsis and starts its help line as a sentence", () => {
    renderRoute("/epic/epic-1", "/epic/:id", <ActionsMenu subject="epic-1" items={[
      { key: "models", label: "Models…", gloss: "each role's model and effort on this epic.", render: () => <p>body</p> },
    ]} />);
    fireEvent.click(screen.getByTestId("actions-open"));
    expect(screen.getByTestId("action-models")).toHaveTextContent("Models…");
    fireEvent.click(screen.getByTestId("action-models"));
    expect(screen.getByRole("dialog", { name: "Models" })).toBeInTheDocument();
    expect(screen.getByTestId("action-drawer-gloss").textContent).toBe("Each role's model and effort on this epic.");
  });

  it("dialogTitle and sentence", () => {
    expect(dialogTitle("Models…")).toBe("Models");
    expect(dialogTitle("Models...")).toBe("Models");
    expect(dialogTitle("Ask a role")).toBe("Ask a role");
    expect(sentence("each role")).toBe("Each role");
    expect(sentence("")).toBe("");
  });
});
