"""Hatch build hook: the wheel ships the Vite bundle (src/edp8/webapp/dist, force-included), so a
bundle older than the SPA sources would ship stale UI silently (adversary finding #15, 2026-09-10).

- dist missing            → build it with `npm --prefix web run build` when npm is on PATH, else fail.
- dist older than web/src → same: rebuild when npm is available, otherwise FAIL the build.
- EDP8_WEB_AUTOBUILD=0    → never run npm; just check (CI that builds the SPA in its own step).
- no web/src beside the package (a trimmed sdist) → nothing to compare; the check is skipped.
"""
from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

from hatchling.builders.hooks.plugin.interface import BuildHookInterface


def _newest(paths: list[Path]) -> float:
    newest = 0.0
    for p in paths:
        if p.is_dir():
            for f in p.rglob("*"):
                if f.is_file():
                    newest = max(newest, f.stat().st_mtime)
        elif p.is_file():
            newest = max(newest, p.stat().st_mtime)
    return newest


class WebBundleFreshness(BuildHookInterface):
    PLUGIN_NAME = "custom"

    def initialize(self, version: str, build_data: dict) -> None:  # noqa: ARG002
        if self.target_name != "wheel":
            return
        root = Path(self.root)
        web = root / "web"
        dist_index = root / "src" / "edp8" / "webapp" / "dist" / "index.html"
        if not (web / "src").is_dir():
            return  # nothing to compare against (trimmed sdist)
        sources = [web / "src", web / "index.html", web / "vite.config.ts", web / "package.json"]
        stale = not dist_index.exists() or dist_index.stat().st_mtime < _newest(sources)
        if not stale:
            return
        why = "missing" if not dist_index.exists() else "older than web/src"
        autobuild = os.environ.get("EDP8_WEB_AUTOBUILD", "1") != "0"
        npm = shutil.which("npm") if autobuild else None
        if not npm:
            raise RuntimeError(
                f"edp8 wheel: the SPA bundle is {why} ({dist_index}). Run `npm --prefix web run build` "
                "(EDP8_WEB_BASE=/ui/) before building, or put npm on PATH so the hook builds it."
            )
        self.app.display_info(f"edp8: SPA bundle {why} — running npm run build")
        env = {**os.environ, "EDP8_WEB_BASE": os.environ.get("EDP8_WEB_BASE", "/ui/")}
        subprocess.run([npm, "--prefix", str(web), "run", "build"], check=True, env=env)
        if not dist_index.exists():
            raise RuntimeError("edp8 wheel: npm run build did not produce dist/index.html")
