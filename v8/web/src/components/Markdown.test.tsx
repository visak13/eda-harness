import { render } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { demoteHeadings, Markdown } from "./Markdown";

describe("Markdown heading demotion (acceptance finding: Library/Doc rendered two h1)", () => {
  it("shifts every body heading one level so the doc title stays the only h1", () => {
    const out = demoteHeadings('<h1 id="a">Craft</h1><p>x</p><h2>Two</h2><h5>Five</h5><h6>Six</h6>');
    expect(out).toBe('<h2 id="a">Craft</h2><p>x</p><h3>Two</h3><h6>Five</h6><h6>Six</h6>');
  });

  it("renders no h1 from a body that opens with a level-one heading, and still strips scripts", () => {
    const { container } = render(<Markdown html={'<h1>Craft</h1><img src=x onerror="alert(1)"><script>1</script>'} />);
    expect(container.querySelector("h1")).toBeNull();
    expect(container.querySelector("h2")?.textContent).toBe("Craft");
    expect(container.querySelector("script")).toBeNull();
    expect(container.querySelector("img")?.getAttribute("onerror")).toBeNull();
  });
});
