import { describe, it, expect } from "vitest";
import { render, screen } from "@testing-library/react";
import { MemoryRouter, Routes, Route } from "react-router";
import {
  DecisionsPage,
  DocPage,
  EpicPage,
  EpicsPage,
  LibraryPage,
  NotFoundPage,
  SeatsPage,
  TicketPage,
} from "./index";

function renderAt(path: string, route: string, element: React.JSX.Element) {
  return render(
    <MemoryRouter initialEntries={[path]}>
      <Routes>
        <Route path={route} element={element} />
      </Routes>
    </MemoryRouter>,
  );
}

describe("route page stubs", () => {
  it.each([
    ["Decisions", <DecisionsPage />],
    ["Epics", <EpicsPage />],
    ["Seats", <SeatsPage />],
    ["Not found", <NotFoundPage />],
  ])("%s renders its h1", (title, el) => {
    render(<MemoryRouter>{el}</MemoryRouter>);
    expect(screen.getByRole("heading", { level: 1 })).toHaveTextContent(title);
  });

  it("EpicPage shows the id from the route", () => {
    renderAt("/epic/e-42", "/epic/:id", <EpicPage />);
    expect(screen.getByRole("heading", { level: 1 })).toHaveTextContent("Epic");
    expect(screen.getByText("e-42")).toBeInTheDocument();
  });

  it("TicketPage shows the id from the route", () => {
    renderAt("/ticket/t-7", "/ticket/:id", <TicketPage />);
    expect(screen.getByText("t-7")).toBeInTheDocument();
  });

  it("DocPage shows the id from the route", () => {
    renderAt("/doc/d-9", "/doc/:id", <DocPage />);
    expect(screen.getByText("d-9")).toBeInTheDocument();
  });

  it("LibraryPage shows the section from the route", () => {
    renderAt("/library/history", "/library/:section", <LibraryPage />);
    expect(screen.getByRole("heading", { level: 1 })).toHaveTextContent("Library");
    expect(screen.getByText("history")).toBeInTheDocument();
  });
});
