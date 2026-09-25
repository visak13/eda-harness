import { describe, it, expect } from "vitest";
import { embedUrl, guardBase, isLoopbackHost, lineLabel, loginUrl, normalizeFile, normalizeFolder, parseCodeLink, parseLine } from "./codeLink";

// epic-91fcd3b370 S3: deep-link parsing and the code-server URL. The folder form is the binding S1
// ruling (dec-ea925a2d30): `/c:/…` — leading slash, lowercase drive, forward slashes.
describe("normalizeFolder", () => {
  it.each([
    [String.raw`C:\Projects\Learning\eda-base3\v8`, "/c:/Projects/Learning/eda-base3/v8"],
    ["C:/Projects/Learning/eda-base3/v8", "/c:/Projects/Learning/eda-base3/v8"],
    ["/C:/Projects/x/", "/c:/Projects/x"],
    ["/c:/Projects/x", "/c:/Projects/x"],
    ["c:\\", "/c:/"],
    ["D:", "/d:/"],
    [String.raw`C:\\a\\b`, "/c:/a/b"],
    ["/home/me/repo/", "/home/me/repo"],
  ])("%s → %s", (raw, want) => expect(normalizeFolder(raw)).toBe(want));

  it.each(["", "  ", "relative/dir", String.raw`\\server\share`, "//server/share", "C:/a/../b"])("rejects %j", (raw) =>
    expect(normalizeFolder(raw)).toBeNull());
});

describe("normalizeFile", () => {
  it("keeps a relative path with forward slashes", () => {
    expect(normalizeFile(String.raw`src\edp8\board.py`)).toBe("src/edp8/board.py");
    expect(normalizeFile("/src/x.py")).toBe("src/x.py");
    expect(normalizeFile("a b/c#d?.py")).toBe("a b/c#d?.py");
  });
  it.each(["", "../etc/passwd", "a/./b", "src/", "C:/abs.py"])("rejects %j", (raw) => expect(normalizeFile(raw)).toBeNull());
});

describe("parseLine", () => {
  it("parses one line and a range, swapping a reversed range", () => {
    expect(parseLine("10")).toEqual({ start: 10, end: 10 });
    expect(parseLine("10-20")).toEqual({ start: 10, end: 20 });
    expect(parseLine(" 20 – 10 ")).toEqual({ start: 10, end: 20 });
  });
  it.each(["", "0", "a", "10-", "-3", "1.5", "10-20-30"])("rejects %j", (raw) => expect(parseLine(raw)).toBeNull());
  it("labels L10 and L10–20", () => {
    expect(lineLabel({ start: 10, end: 10 })).toBe("L10");
    expect(lineLabel({ start: 10, end: 20 })).toBe("L10–20");
    expect(lineLabel(null)).toBe("");
  });
});

describe("parseCodeLink", () => {
  it("reads folder, file and line, and names the unusable ones", () => {
    const l = parseCodeLink("?folder=C%3A%5CProjects%5Cv8&file=src%2Fa.py&line=10-20");
    expect(l).toEqual({ folder: "/c:/Projects/v8", file: "src/a.py", line: { start: 10, end: 20 }, invalid: [] });
    expect(parseCodeLink("?folder=rel&file=..%2Fx&line=zz").invalid).toEqual(["folder", "file", "line"]);
    expect(parseCodeLink("")).toEqual({ folder: null, file: null, line: null, invalid: [] });
  });
});

describe("embedUrl", () => {
  const BASE = "http://127.0.0.1:9410/";
  const payloadOf = (u: string) => JSON.parse(new URL(u).searchParams.get("payload")!);

  // t-6356c06c40: a plain open sends no folder, so code-server reopens its last folder/workspace
  // (and only with no history its CLI default); any ?folder= would override that memory.
  it.each(["", "?line=10", "?folder=", "?file="])("a plain open (%s) sends no folder, so code-server reopens its last folder", search => {
    const u = embedUrl(BASE, parseCodeLink(search), String.raw`C:\Projects\Learning\eda-base3\v8`);
    expect(u).toBe("http://127.0.0.1:9410/");
  });

  it("a deep-linked file with no folder resolves against the board's own tree in the /c:/ form", () => {
    const u = embedUrl(BASE, parseCodeLink("?file=src/edp8/board.py&line=7"), String.raw`C:\Projects\Learning\eda-base3\v8`);
    expect(new URL(u).searchParams.get("folder")).toBe("/c:/Projects/Learning/eda-base3/v8");
    expect(payloadOf(u)).toEqual([
      ["openFile", "vscode-remote://127.0.0.1:9410/c:/Projects/Learning/eda-base3/v8/src/edp8/board.py:7"],
      ["gotoLineMode", "true"],
    ]);
  });

  it.each(["//server/share/repo", "relative", "C:/a/../b"])("never opens a fallback file for rejected root %s", folder => {
    const link = parseCodeLink(`?${new URLSearchParams({ folder, file: "a.py", line: "10" })}`);
    const url = new URL(embedUrl(BASE, link, "C:/board/v8"));
    expect(link.invalid).toContain("folder");
    expect(url.searchParams.has("folder")).toBe(false);
    expect(url.searchParams.has("payload")).toBe(false);
  });

  it("opens the file at the range's start line through the workbench payload", () => {
    const u = embedUrl(BASE, parseCodeLink("?folder=C:/Projects/v8&file=src/edp8/board.py&line=10-20"), null);
    expect(new URL(u).searchParams.get("folder")).toBe("/c:/Projects/v8");
    expect(payloadOf(u)).toEqual([
      ["openFile", "vscode-remote://127.0.0.1:9410/c:/Projects/v8/src/edp8/board.py:10"],
      ["gotoLineMode", "true"],
    ]);
  });

  it("a file without a line opens without gotoLineMode; a line without a file is ignored", () => {
    expect(payloadOf(embedUrl(BASE, parseCodeLink("?folder=/c:/r&file=a.py"), null))).toEqual([["openFile", "vscode-remote://127.0.0.1:9410/c:/r/a.py"]]);
    expect(new URL(embedUrl(BASE, parseCodeLink("?folder=/c:/r&line=5"), null)).searchParams.has("payload")).toBe(false);
  });

  it("percent-encodes awkward names in the folder and the file URI, and keeps the port from the board", () => {
    const u = embedUrl("http://127.0.0.1:9555/", parseCodeLink("?folder=C:/My%20Repo%20%26%20co&file=a%20b/c%23d%3F.py&line=3"), null);
    expect(new URL(u).searchParams.get("folder")).toBe("/c:/My Repo & co");
    expect(u).toContain("folder=/c:/My%20Repo%20%26%20co&");
    expect(payloadOf(u)[0][1]).toBe("vscode-remote://127.0.0.1:9555/c:/My%20Repo%20%26%20co/a%20b/c%23d%3F.py:3");
  });
});

describe("isLoopbackHost", () => {
  it.each(["127.0.0.1", "localhost", "::1", "[::1]", "127.1.2.3"])("%s is the board host", (h) => expect(isLoopbackHost(h)).toBe(true));
  it.each(["192.168.1.5", "board.example", "100.64.0.1", "127.0.0.1.nip.io"])("%s is remote", (h) => expect(isLoopbackHost(h)).toBe(false));
});

// s-17c13096e5: the guard login URL and the page-host guard base
describe("loginUrl", () => {
  it("keeps a bare / as the redirect target (code-server reopens its last folder)", () => {
    const u = new URL(loginUrl("http://127.0.0.1:9410/", "1.ab.cd"));
    expect(u.pathname).toBe("/__edp/login");
    expect(u.searchParams.get("t")).toBe("1.ab.cd");
    expect(u.searchParams.get("next")).toBe("/");
  });
  it("carries a deep link's path and query, encoded once, as next", () => {
    const src = embedUrl("http://127.0.0.1:9410/", parseCodeLink("?folder=C:/My Projects/v8&file=a b.py&line=3"), null);
    const u = new URL(loginUrl(src, "t"));
    expect(u.origin).toBe("http://127.0.0.1:9410");
    const next = u.searchParams.get("next")!;
    expect(next.startsWith("/?folder=")).toBe(true);
    expect(next).not.toContain(" ");
    expect(new URL(next, "http://127.0.0.1:9410").toString()).toBe(src);
  });
});

describe("guardBase", () => {
  it("frames the guard under the page's own loopback name, so the SameSite=Strict cookie is same-site", () => {
    expect(guardBase("http://127.0.0.1:9410/", "localhost")).toBe("http://localhost:9410/");
    expect(guardBase("http://127.0.0.1:9410/", "127.0.0.1")).toBe("http://127.0.0.1:9410/");
    expect(guardBase("http://127.0.0.1:9410/", "127.0.0.2")).toBe("http://127.0.0.1:9410/");
  });
});
