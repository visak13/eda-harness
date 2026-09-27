// t-cf72f6962f: the e2e board's env is an allowlist (web/e2e/hermeticEnv.ts). A seat shell's fleet
// pointers must never reach a spec board, or it reads the fleet tokens.json/code.json and 401s.
import path from "node:path";
import { describe, expect, it } from "vitest";
import { hermeticEnv } from "../../e2e/hermeticEnv";

const HOME = path.join("C:", "tmp", "edp8-e2e-abc");

// Shaped like a real pool seat shell (Windows spellings included).
const FLEET_SHELL: NodeJS.ProcessEnv = {
  Path: "C:\\Windows\\system32;C:\\Users\\me\\.local\\bin",
  SystemRoot: "C:\\Windows",
  windir: "C:\\Windows",
  ComSpec: "C:\\Windows\\system32\\cmd.exe",
  TEMP: "C:\\Users\\me\\AppData\\Local\\Temp",
  TMP: "C:\\Users\\me\\AppData\\Local\\Temp",
  USERPROFILE: "C:\\Users\\me",
  LOCALAPPDATA: "C:\\Users\\me\\AppData\\Local",
  APPDATA: "C:\\Users\\me\\AppData\\Roaming",
  UV_CACHE_DIR: "D:\\uv-cache",
  EDP_HOME: "C:\\Work\\eda-base3",
  EDP8_HOME: "C:\\Work\\eda-base3\\v8",
  EDP8_RUN_DIR: "C:\\Work\\eda-base3\\v8\\.run",
  EDP_AGENT_HOME: "C:\\Work\\eda-base3\\v8",
  EDP_POOL_URL: "http://127.0.0.1:9301",
  EDP_BROKER_URL: "http://127.0.0.1:9300",
  EDP8_BOARD_URL: "http://127.0.0.1:9400",
  EDP8_TOKEN: "fleet-seat-token",
  EDP8_TOKENS: "C:\\Work\\eda-base3\\v8\\tokens.json",
  EDP_HANDLE: "engineer.t-x",
  EDP8_PARTICIPANT: "engineer.t-x",
  EDP8_ADMIN_TOKEN: "fleet-admin",
  EDP8_USAGE_CONFIG: "C:\\fleet\\usage.toml",
  EDP8_BOARD_CMD: "C:\\venv\\edp8-board.exe",
  Edp_Pool_Log_Dir: "C:\\fleet\\logs", // odd casing is still an EDP* name
  ANTHROPIC_API_KEY: "sk-secret",
  CLAUDE_CONFIG_DIR: "C:\\Users\\me\\.claude-pool",
};

describe("hermeticEnv", () => {
  const out = hermeticEnv(FLEET_SHELL, HOME);

  it("passes none of the fleet pointers or seat credentials", () => {
    for (const k of ["EDP_POOL_URL", "EDP_BROKER_URL", "EDP8_BOARD_URL", "EDP8_TOKEN", "EDP8_TOKENS", "EDP_HANDLE",
      "EDP8_PARTICIPANT", "EDP8_ADMIN_TOKEN", "EDP8_USAGE_CONFIG", "EDP8_BOARD_CMD", "EDP_AGENT_HOME", "Edp_Pool_Log_Dir"]) {
      expect(out, k).not.toHaveProperty(k);
    }
    const leaked = Object.entries(out).filter(([, v]) => typeof v === "string" && /eda-base3|fleet|9301|9300|9400/.test(v));
    expect(leaked).toEqual([]);
  });

  it("gives the board a private home and run dir", () => {
    expect(out.EDP_HOME).toBe(HOME);
    expect(out.EDP8_HOME).toBe(HOME);
    expect(out.EDP8_RUN_DIR).toBe(path.join(HOME, ".run"));
    expect(Object.keys(out).filter((k) => k.toUpperCase().startsWith("EDP")).sort()).toEqual(["EDP8_HOME", "EDP8_RUN_DIR", "EDP_HOME"]);
  });

  it("keeps only the allowlisted OS basics, in their original spelling", () => {
    expect(out.Path).toBe(FLEET_SHELL.Path);
    expect(out.SystemRoot).toBe("C:\\Windows");
    expect(out.ComSpec).toBe(FLEET_SHELL.ComSpec);
    expect(out.LOCALAPPDATA).toBe(FLEET_SHELL.LOCALAPPDATA);
    expect(out.UV_CACHE_DIR).toBe("D:\\uv-cache");
    expect(out).not.toHaveProperty("ANTHROPIC_API_KEY");
    expect(out).not.toHaveProperty("CLAUDE_CONFIG_DIR");
  });
});

describe("seedAgentHome (t-67d19c5807)", () => {
  it("copies the repo's role cards and models.json into a private <home>/agent-home, leaving the repo alone", async () => {
    const fs = await import("node:fs");
    const os = await import("node:os");
    const { seedAgentHome } = await import("../../e2e/hermeticEnv");
    const repo = fs.mkdtempSync(path.join(os.tmpdir(), "repo-"));
    const home = fs.mkdtempSync(path.join(os.tmpdir(), "home-"));
    try {
      fs.mkdirSync(path.join(repo, ".claude", "commands"), { recursive: true });
      for (const f of ["engineer.md", "qa.md", "notes.txt"]) fs.writeFileSync(path.join(repo, ".claude", "commands", f), f);
      fs.writeFileSync(path.join(repo, "models.json"), "{}");
      const agentHome = seedAgentHome(repo, home);
      expect(agentHome).toBe(path.join(home, "agent-home"));
      expect(fs.readdirSync(path.join(agentHome, ".claude", "commands")).sort()).toEqual(["engineer.md", "qa.md"]);
      expect(fs.readFileSync(path.join(agentHome, ".claude", "commands", "qa.md"), "utf8")).toBe("qa.md");
      expect(fs.readFileSync(path.join(agentHome, "models.json"), "utf8")).toBe("{}"); // the role-model picker's catalog
      expect(fs.readdirSync(path.join(repo, ".claude", "commands")).sort()).toEqual(["engineer.md", "notes.txt", "qa.md"]);
    } finally {
      fs.rmSync(repo, { recursive: true, force: true });
      fs.rmSync(home, { recursive: true, force: true });
    }
  });
});
