import { render } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { demoteHeadings, keepTokensWhole, Markdown } from "./Markdown";

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

  it("keeps an attachment id the author wrote inside a sentence, linked, and strips only the trailing one", async () => {
    const { linkifyMessageHtml } = await import("./Markdown");
    const out = linkifyMessageHtml("<p>attachment id art-abc1234, and the rest art-dead0001</p>", ["art-abc1234", "art-dead0001"]);
    const doc = new DOMParser().parseFromString(out, "text/html");
    expect(doc.querySelector("p")?.textContent).toBe("attachment id art-abc1234, and the rest");
    expect(Array.from(doc.querySelectorAll("a")).map((a) => a.getAttribute("href"))).toEqual(["/artifact/art-abc1234"]);
  });

  it("stripTokens drops only the run of attachment ids that ends a plain message", async () => {
    const { stripTokens } = await import("./Conversation");
    const a = (id: string) => ({ id }) as never;
    expect(stripTokens("attachment id art-abc1234, and more art-abc1234 art-dead0001", [a("art-abc1234"), a("art-dead0001")]))
      .toBe("attachment id art-abc1234, and more");
    expect(stripTokens("no tokens here", [a("art-abc1234")])).toBe("no tokens here");
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

// t-cb431765fc (c-894f88bd1b): a document fits its column — no sideways scroller inside the design review.
// jsdom does no layout, so this pins the rules; scripts/reader_walk.mjs measures the pixels on a real board.
describe("document Markdown fits its column", () => {
  it("wraps code, table cells and inline code, and nothing in the doc or review CSS scrolls sideways", async () => {
    const { readFileSync } = await import("node:fs");
    const { resolve } = await import("node:path");
    const md = readFileSync(resolve(__dirname, "Markdown.module.css"), "utf-8");
    const review = readFileSync(resolve(__dirname, "DesignReview.module.css"), "utf-8");
    const rule = (sel: string) => md.split(`.docMd :global(${sel}) {`).slice(1).map((r) => r.split("}")[0]).join(";");
    expect(rule("pre")).toMatch(/white-space:\s*pre-wrap/);
    expect(rule("pre")).toMatch(/overflow-wrap:\s*anywhere/);
    expect(rule("code")).toMatch(/overflow-wrap:\s*anywhere/);
    expect(md).toMatch(/:global\(td\) \{[^}]*overflow-wrap:\s*anywhere/);
    expect(rule("img")).toMatch(/max-width:\s*100%/);
    for (const css of [md, review]) expect(css).not.toMatch(/overflow-x:\s*(auto|scroll)/);
  });
});

// architect m-7ae758c02c: a token must not break at its hyphen or slash.
describe("keepTokensWhole", () => {
  it("keeps one short code token and a slash command on one line, and leaves long or spaced code alone", () => {
    const out = keepTokensWhole('<p>run <code>your-pc.tail1234.ts.net</code> or /doc-write now; <code>two words-here</code> <code>plain</code> <a href="/x-y">l</a></p>');
    expect(out).toContain('<code style="white-space:nowrap">your-pc.tail1234.ts.net</code>');
    expect(out).toContain('<span style="white-space:nowrap">/doc-write</span>');
    expect(out).toContain("<code>two words-here</code>");
    expect(out).toContain("<code>plain</code>");
    expect(out).toContain('<a href="/x-y">');
  });
});
