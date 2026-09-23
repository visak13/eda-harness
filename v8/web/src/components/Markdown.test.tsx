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

// S17 c-b1f32f8b33: chat messages render the board's Markdown HTML; bare URLs and art- tokens in
// text become links (never inside code), attachment tokens are stripped, scripts never survive.
describe("message Markdown", () => {
  it("linkifies bare URLs and artifact tokens in text only, and strips attachment ids", async () => {
    const { linkifyMessageHtml } = await import("./Markdown");
    const out = linkifyMessageHtml('<p>see https://x.test/a and art-abc1234 and art-dead0001</p><pre><code>https://in.code</code></pre>', ["art-dead0001"]);
    const doc = new DOMParser().parseFromString(out, "text/html");
    const hrefs = Array.from(doc.querySelectorAll("a")).map((a) => a.getAttribute("href"));
    expect(hrefs).toEqual(["https://x.test/a", "/artifact/art-abc1234"]);
    expect(out).not.toContain("art-dead0001");
    expect(doc.querySelector("code")?.innerHTML).toBe("https://in.code");
  });

  it("renders a table and a code fence and drops a script the server would never send", async () => {
    const { MessageMarkdown } = await import("./Markdown");
    const { MemoryRouter } = await import("react-router");
    const { container } = render(<MemoryRouter><MessageMarkdown html={'<table><tr><td>gap</td></tr></table><pre><code class="language-ts">x</code></pre><script>1</script>'} /></MemoryRouter>);
    expect(container.querySelector("table td")?.textContent).toBe("gap");
    expect(container.querySelector("pre code")?.textContent).toBe("x");
    expect(container.querySelector("script")).toBeNull();
  });
});
