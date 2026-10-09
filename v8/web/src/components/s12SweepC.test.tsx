import { describe, it, expect, vi } from "vitest";
import { render, screen, fireEvent, act } from "@testing-library/react";
import { readFileSync } from "node:fs";
import { Drawer } from "./Drawer";
import { defaultFraming } from "./PageFrame";
import { dropLeadingTitle, stripDesignPrefix } from "./dropLeadingTitle";
import { ADMIN_TABS } from "../pages/admin/Admin";
import { PAGES } from "../copy/pages";

describe("sweep #6: Escape closes a drawer whose focus fell to body", () => {
  it("closes on Escape with focus on <body>", () => {
    const onClose = vi.fn();
    render(<Drawer open onClose={onClose} title="Design"><p>body</p></Drawer>);
    act(() => { (document.activeElement as HTMLElement | null)?.blur(); });
    expect(document.activeElement).toBe(document.body);
    fireEvent.keyDown(document.body, { key: "Escape" });
    expect(onClose).toHaveBeenCalledTimes(1);
  });
});

describe("sweep #11: every shell route has its own screen-reader description", () => {
  it.each(["/admin", "/design", "/records/dec-1", "/artifact/art-1"])("%s is not the Decisions sentence", (p) => {
    expect(defaultFraming(p)).not.toMatch(/Decisions collects/);
  });
  it("names the admin and design pages", () => {
    expect(defaultFraming("/admin")).toMatch(/teammates/);
    expect(defaultFraming("/design")).toMatch(/workflows/);
  });
});

describe("sweep #14: copy", () => {
  it("drops a body heading that repeats the doc title", () => {
    expect(dropLeadingTitle("<h2>Plan: X</h2><p>a</p>", "Plan: X")).toBe("<p>a</p>");
    expect(dropLeadingTitle("<h1>Plan: X</h1><p>a</p>", "Plan: X")).toBe("<p>a</p>");
    expect(dropLeadingTitle("<h2>Other</h2><p>a</p>", "Plan: X")).toBe("<h2>Other</h2><p>a</p>");
  });
  it("does not say Design twice", () => {
    expect(stripDesignPrefix("Design: Make Heronry trustworthy")).toBe("Make Heronry trustworthy");
    expect(stripDesignPrefix("Make it")).toBe("Make it");
  });
  it("the Admin help lists the tabs in the order they appear", () => {
    const help = PAGES.admin.items.find((i) => i.key === "tabs")!.label;
    expect(help).toBe(ADMIN_TABS.map((t) => t.label).join(" · "));
  });
});

describe("sweep #2: the source select is themed and bounded", () => {
  it("has a themed, width-bounded module style", () => {
    const css = readFileSync("src/components/DocumentSource.module.css", "utf8");
    expect(css).toMatch(/\.select[^}]*background:\s*var\(--panel\)/);
    expect(css).toMatch(/\.select[^}]*max-width:\s*100%/);
    expect(css).toMatch(/\.select[^}]*min-width:\s*0/);
  });
  it("renders with the module class", async () => {
    const { DocumentSource } = await import("./DocumentSource");
    const { QueryClient, QueryClientProvider } = await import("@tanstack/react-query");
    render(<QueryClientProvider client={new QueryClient()}><DocumentSource docId="d1" version={1} /></QueryClientProvider>);
    expect(screen.getByLabelText("Conversation source").className).not.toBe("");
  });
});
