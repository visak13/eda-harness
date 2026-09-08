import { describe, it, expect } from "vitest";
import { screen } from "@testing-library/react";
import { renderRoute } from "./testUtils";
import { NotFoundPage } from "./index";

describe("NotFoundPage", () => {
  it("renders the not-found header from the barrel", () => {
    renderRoute("/nope", "*", <NotFoundPage />);
    expect(screen.getByText("Not found")).toBeInTheDocument();
    expect(screen.getByText("No such page on the board.")).toBeInTheDocument();
  });
});
