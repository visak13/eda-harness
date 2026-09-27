"""PII scan of the built site (design-e963c656f5 §4.15: the site is built only from the public tree, and the PII
scan covers it). The build fails on a hit (mkdocs hook `on_post_build`) and the site workflow runs it again
before any deploy, next to `gitleaks dir site/` with the repo's gitleaks rules once they exist.

Rules: a Windows or POSIX user-profile path, a `C:\\Projects` path, an email address that is not a placeholder
or a noreply address, a Tailscale machine name, and the name of the OS user running the build. Usage:
    python pii_scan.py <dir>        exit 0 clean, 1 findings (one line each), 2 usage
"""
from __future__ import annotations

import getpass
import re
import sys
from pathlib import Path

TEXT_SUFFIXES = {".html", ".htm", ".js", ".json", ".xml", ".txt", ".css", ".md", ".svg", ".map", ".yml", ".yaml"}

RULES: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("windows user path", re.compile(r"[A-Za-z]:(?:\\\\|\\|/)Users(?:\\\\|\\|/)(?!<|\{|%|Public\b|Default\b)[\w.-]+",
                                     re.I)),
    ("posix home path", re.compile(r"(?<![\w.])/(?:home|Users)/(?!<|\{|\$|runner\b|user\b|you\b|me\b)[a-z][\w.-]+/",
                                   re.I)),
    ("projects path", re.compile(r"[A-Za-z]:(?:\\\\|\\|/)Projects(?:\\\\|\\|/)", re.I)),
    ("email", re.compile(r"(?<![\w.+-])[\w.+-]+@(?!example\.(?:com|org)\b|users\.noreply\.github\.com\b|"
                         r"noreply\b|anthropic\.com\b|remotion\.dev\b)[A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)*\.[A-Za-z]{2,}\b")),
    ("tailnet hostname", re.compile(r"\b(?!machine\b|<)[a-z0-9-]+\.(?!tailnet\b|<)[a-z0-9-]+\.ts\.net\b", re.I)),
)
#: the theme's own prebuilt bundles (MkDocs Material's licence headers and source maps name its public author);
#: nothing of ours is written under them
VENDOR_PREFIXES = ("assets/javascripts/", "assets/stylesheets/")
#: ignore these false positives: package names that look like emails (npm `@scope/pkg@1.2.3`)
_EMAIL_OK = re.compile(r"@[\w.-]+/[\w.-]+@\d")


def _user_rule() -> tuple[str, re.Pattern[str]] | None:
    try:
        name = getpass.getuser()
    except Exception:  # noqa: BLE001 — no user name: no rule
        return None
    if len(name) < 4 or name.lower() in {"runner", "root", "user", "admin", "build", "docker"}:
        return None
    return ("os user name", re.compile(rf"(?<![A-Za-z0-9]){re.escape(name)}(?![A-Za-z0-9])", re.I))


def scan(root: Path) -> list[str]:
    rules = list(RULES)
    user = _user_rule()
    if user:
        rules.append(user)
    hits: list[str] = []
    for p in sorted(root.rglob("*")):
        if not p.is_file() or p.suffix.lower() not in TEXT_SUFFIXES:
            continue
        if p.relative_to(root).as_posix().startswith(VENDOR_PREFIXES):
            continue
        text = p.read_text(encoding="utf-8", errors="replace")
        for label, rx in rules:
            for m in rx.finditer(text):
                if label == "email" and _EMAIL_OK.search(text[max(0, m.start() - 60):m.end() + 20]):
                    continue
                line = text.count("\n", 0, m.start()) + 1
                hits.append(f"{p.relative_to(root).as_posix()}:{line}: {label}: {m.group(0)[:80]}")
    return hits


def main(argv: list[str]) -> int:
    if len(argv) != 1 or not Path(argv[0]).is_dir():
        print("usage: pii_scan.py <built site dir>", file=sys.stderr)
        return 2
    hits = scan(Path(argv[0]))
    for h in hits:
        print(h)
    print(f"pii scan: {len(hits)} finding(s) in {argv[0]}", file=sys.stderr)
    return 1 if hits else 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
