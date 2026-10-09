// S9 guard G2 (memory git-bash-mangles-web-base): Git Bash rewrites `/ui/` into `C:/Program Files/Git/ui/` before vite
// sees it, which blanked the shared SPA. A base is a URL path or nothing.
const URL_PATH = /^\/([A-Za-z0-9._-]+\/)*$/;

export function resolveBase(raw: string | undefined): string {
  const v = raw ?? "/ui/";
  if (!URL_PATH.test(v)) {
    throw new Error(`EDP8_WEB_BASE=${v} is not a URL path (Git Bash rewrites /ui/ into a Windows path); build from PowerShell`);
  }
  return v;
}
