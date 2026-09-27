"""`heronry import --from <v8 dir>`: copy a source checkout's state into this install (design-e963c656f5
§4.13, S3 s-870e401942).

Dry run by default: it prints what would be copied where (new / replace / same) and what the DB holds;
``--apply`` does it. The source is only ever read: the DB is copied with SQLite's online backup from a
read-only connection (a consistent snapshot even while the old board runs), every other file with a
plain read. Rollback is starting the old checkout on its untouched data.

What moves:

* ``.data/edp8.db`` → the ``EDP8_DB`` path (backup API), plus the ``.vec`` search index beside it;
* the rest of ``.data`` (uploads, broker data, pool state, …) → the data dir, minus logs, pid and lock
  files and SQLite side files; ``v8/uploads`` merges into ``<data>/uploads`` without overwriting;
* ``tokens.json`` and ``.data/human-tokens.txt`` → the secrets dir (private files);
* ``slack_map.json``, ``ui-settings.json``, ``ui-avatars.json``, ``models.json`` → their settings paths;
* ``.env`` → config.toml for declared, config-able, non-path settings; a secret (the admin token) goes
  to its private file, never config.toml; anything else is reported as skipped, with the reason;
* the pool's claude transcripts (``<old claude config>/projects/<key of the v8 dir>``) → the new claude
  config dir under the key of this install's agent home, so a resumed seat finds its conversation
  (v0.9.1, s-dbe96f11cd: `claude --resume` looks only under the cwd's key).

Two sources that land on one target keep the first: ``.data/models.json`` (the live catalog) beats the
root ``models.json`` template.
"""

from __future__ import annotations

import hashlib
import re
import shutil
import sqlite3
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from edp_contracts.settings import secrets as secret_files
from edp_contracts.settings._core import _coerce

from . import settings

#: never copied out of .data: logs, pids, locks, SQLite side files (the DB goes by backup)
_SKIP = re.compile(r"(\.(log|err)(\.\d+)?|\.pid|\.lock|-wal|-shm|-journal)$")
_SKIP_NAMES = {"edp8.db", "edp8.db.vec", "human-tokens.txt"}
_SECRETS = {"tokens.json", "human-tokens.txt"}


@dataclass
class Item:
    what: str
    src: Path
    dst: Path
    kind: str = "file"          # file | tree | db | secret
    action: str = ""            # new | replace | same | merge
    size: int = 0
    note: str = ""


def _long(p: Path) -> Path:
    """Windows: the extended-length form, so a .data tree deeper than MAX_PATH (a v8 host has one under
    .data/code/spike) still copies; elsewhere the path itself."""
    if sys.platform != "win32":
        return p
    s = str(p.resolve())
    return Path(s if s.startswith("\\\\?\\") else ("\\\\?\\UNC\\" + s[2:] if s.startswith("\\\\") else "\\\\?\\" + s))


def _digest(p: Path) -> str:
    h = hashlib.sha256()
    with p.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _tree_files(root: Path) -> list[Path]:
    return [p for p in _long(root).rglob("*") if p.is_file() and not _SKIP.search(p.name)]


def _classify(it: Item) -> Item:
    if it.kind == "tree":
        files = _tree_files(it.src)
        it.size = sum(f.stat().st_size for f in files)
        it.action = "merge" if it.dst.exists() else "new"
        it.note = f"{len(files)} files"
    else:
        it.size = it.src.stat().st_size
        if not it.dst.exists():
            it.action = "new"
        elif it.kind != "db" and _digest(it.src) == _digest(it.dst):
            it.action = "same"
        else:
            it.action = "replace"
    return it


def _open_ro(db: Path) -> sqlite3.Connection:
    """A read-only connection that leaves the source byte-unchanged. With no -wal beside it (the old board
    stopped cleanly) the file is opened `immutable`, so SQLite creates no -wal/-shm; with a -wal (the old
    board still runs, or crashed) it is opened `mode=ro`, which reads the WAL too, and SQLite may touch
    the shared-memory index it already has."""
    live = db.with_name(db.name + "-wal").exists()
    return sqlite3.connect(f"{db.resolve().as_uri()}?{'mode=ro' if live else 'immutable=1'}", uri=True)


def db_counts(db: Path) -> dict[str, int]:
    """Epics, tickets and participants in a board DB, read-only."""
    c = _open_ro(db)
    try:
        return {"epics": c.execute("SELECT count(*) FROM ticket WHERE kind='epic'").fetchone()[0],
                "tickets": c.execute("SELECT count(*) FROM ticket").fetchone()[0],
                "participants": c.execute("SELECT count(*) FROM participant").fetchone()[0]}
    finally:
        c.close()


def cwd_key(p: Path) -> str:
    """Claude Code's project folder name for a cwd: every non-alphanumeric character becomes '-'."""
    return "".join(c if c.isalnum() else "-" for c in str(p))


def _old_claude_config(src: Path) -> Path:
    """The source fleet's pool claude config dir: its .env's EDP_CLAUDE_CONFIG_DIR, else the dev default
    <repo>/edp-pool/.claude-pool beside the v8 folder."""
    raw = read_dotenv(src / ".env").get("EDP_CLAUDE_CONFIG_DIR")
    return Path(raw).expanduser() if raw else src.parent / "edp-pool" / ".claude-pool"


def plan(src: Path) -> list[Item]:
    data = src / ".data"
    items: list[Item] = []
    db = data / "edp8.db"
    if db.is_file():
        target = Path(settings.get("EDP8_DB"))
        items.append(Item("board DB", db, target, "db"))
        if (data / "edp8.db.vec").is_file():
            items.append(Item("search index", data / "edp8.db.vec", target.with_name(target.name + ".vec")))
    if data.is_dir():
        for child in sorted(data.iterdir()):
            if child.name in _SKIP_NAMES or _SKIP.search(child.name):
                continue
            items.append(Item(f".data/{child.name}", child, settings.data_dir() / child.name,
                              "tree" if child.is_dir() else "file"))
    if (src / "uploads").is_dir():
        items.append(Item("uploads (legacy dir)", src / "uploads", settings.data_dir() / "uploads", "tree"))
    for name, dst in (("tokens.json", Path(settings.get("EDP8_TOKENS"))),
                      (".data/human-tokens.txt", settings.secrets_dir() / "human-tokens.txt"),
                      ("slack_map.json", Path(settings.get("EDP8_SLACK_MAP"))),
                      ("ui-settings.json", Path(settings.get("EDP8_UI_SETTINGS"))),
                      ("ui-avatars.json", settings.agent_home() / "ui-avatars.json"),
                      ("models.json", Path(settings.get("EDP_MODELS_CONFIG") or settings.data_dir() / "models.json"))):
        p = src / name
        if p.is_file():
            items.append(Item(name, p, dst, "secret" if p.name in _SECRETS else "file"))
    transcripts = _old_claude_config(src) / "projects" / cwd_key(src)
    if transcripts.is_dir():
        new_cfg = Path(settings.get("EDP_CLAUDE_CONFIG_DIR"))
        items.append(Item("claude transcripts", transcripts,
                          new_cfg / "projects" / cwd_key(settings.agent_home()), "tree"))
    seen: set[str] = set()
    kept: list[Item] = []
    for it in items:  # first source wins a shared target (.data/models.json over the root template)
        key = str(it.dst.resolve()).casefold()
        if key not in seen:
            seen.add(key)
            kept.append(it)
    return [_classify(it) for it in kept]


def read_dotenv(p: Path) -> dict[str, str]:
    out: dict[str, str] = {}
    if not p.is_file():
        return out
    for line in p.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, _, v = line.partition("=")
        k = k.strip().removeprefix("export ").strip()
        v = v.strip()
        if len(v) >= 2 and v[0] == v[-1] and v[0] in "'\"":
            v = v[1:-1]
        out[k] = v
    return out


def plan_env(src: Path) -> tuple[dict[str, Any], dict[str, str], list[tuple[str, str]]]:
    """(.env → config.toml updates, secrets by env name, [(env name, why skipped)])."""
    updates: dict[str, Any] = {}
    secret_vals: dict[str, str] = {}
    skipped: list[tuple[str, str]] = []
    for name, raw in read_dotenv(src / ".env").items():
        try:
            s = settings.setting(name)
        except settings.SettingsError:
            skipped.append((name, "not a declared setting: set it in the environment if still wanted"))
            continue
        if s.secret:
            if name == "EDP8_ADMIN_TOKEN":
                secret_vals[name] = raw
            else:
                skipped.append((name, "a secret: set it through the admin UI or the environment"))
        elif s.env_only:
            skipped.append((name, "environment-only"))
        elif s.type == "path":
            skipped.append((name, "a path into the source layout: this install has its own"))
        else:
            try:
                updates[s.key] = _coerce(s, raw)
            except Exception as e:  # noqa: BLE001
                skipped.append((name, f"value refused: {e}"))
    return updates, secret_vals, skipped


def _fmt(n: int) -> str:
    for unit in ("B", "KB", "MB", "GB"):
        if n < 1024 or unit == "GB":
            return f"{n:.0f} {unit}" if unit == "B" else f"{n:.1f} {unit}"
        n /= 1024  # type: ignore[assignment]
    return str(n)


def report(src: Path, items: list[Item], env: tuple[dict[str, Any], dict[str, str], list[tuple[str, str]]]) -> None:
    print(f"import from {src}")
    print(f"into        {settings.home() or settings.config_dir()}  (data {settings.data_dir()})\n")
    for it in items:
        extra = f"  {it.note}" if it.note else ""
        print(f"  {it.action:<8} {it.what:<28} {_fmt(it.size):>9}  -> {it.dst}{extra}")
        if it.kind == "db":
            print(f"           source holds {db_counts(it.src)}")
            if it.src.with_name(it.src.name + "-wal").exists():
                print("           note: the source DB has a -wal (its board is running or stopped uncleanly); the copy "
                      "is a consistent snapshot, but stop the old services first for the final cutover")
            if it.dst.exists():
                print(f"           target holds {db_counts(it.dst)} (it is replaced; a copy goes to backups/)")
    updates, secret_vals, skipped = env
    if updates or secret_vals or skipped:
        print("\n  .env -> config.toml")
        for k, v in sorted(updates.items()):
            print(f"    set      {k} = {v!r}")
        for name in secret_vals:
            print(f"    secret   {name} -> {settings.admin_token_file()} (value not shown)")
        for name, why in skipped:
            print(f"    skip     {name}: {why}")


def _copy_db(src: Path, dst: Path) -> None:
    dst.parent.mkdir(parents=True, exist_ok=True)
    if dst.exists():
        backups = settings.data_dir() / "backups"
        backups.mkdir(parents=True, exist_ok=True)
        old, keep = _open_ro(dst), sqlite3.connect(backups / f"{dst.stem}-pre-import{dst.suffix}")
        try:
            old.backup(keep)  # the backup API also carries what the target's -wal still held
        finally:
            keep.close()
            old.close()
        dst.unlink()
    # v0.9.1: a stale -wal/-shm beside the replaced file is replayed over the imported DB (the import
    # then reported 0 epics), so they go with it
    for side in ("-wal", "-shm", "-journal"):
        dst.with_name(dst.name + side).unlink(missing_ok=True)
    tmp = dst.with_name(dst.name + ".importing")
    tmp.unlink(missing_ok=True)
    source = _open_ro(src)
    target = sqlite3.connect(tmp)
    try:
        source.backup(target)
        ok = target.execute("PRAGMA integrity_check").fetchone()[0]
        if ok != "ok":
            raise RuntimeError(f"imported DB failed integrity_check: {ok}")
    finally:
        target.close()
        source.close()
    tmp.replace(dst)


def apply(items: list[Item], env: tuple[dict[str, Any], dict[str, str], list[tuple[str, str]]]) -> None:
    from .setup import write_config

    for it in items:
        if it.action == "same":
            continue
        if it.kind == "db":
            _copy_db(it.src, it.dst)
        elif it.kind == "tree":
            for f in _tree_files(it.src):
                d = it.dst / f.relative_to(_long(it.src))
                if d.exists() and it.what.startswith("uploads (legacy"):
                    continue  # the .data copy wins over the legacy dir
                d = _long(d)
                d.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(f, d)
        elif it.kind == "secret":
            it.dst.unlink(missing_ok=True)
            secret_files.write_secret(it.dst, it.src.read_text(encoding="utf-8"))
        else:
            it.dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(it.src, it.dst)
    updates, secret_vals, _ = env
    if updates:
        write_config(updates)
    if "EDP8_ADMIN_TOKEN" in secret_vals:
        f = settings.admin_token_file()
        f.unlink(missing_ok=True)
        secret_files.write_secret(f, secret_vals["EDP8_ADMIN_TOKEN"])


def main(argv: list[str]) -> int:
    from . import launcher
    from .cli import _split

    _, opts = _split(argv)
    raw = opts.get("from")
    if not isinstance(raw, str):
        print("usage: heronry import --from <v8 dir> [--apply] [--force]", file=sys.stderr)
        return 2
    src = Path(raw).expanduser().resolve()
    if not (src / ".data").is_dir() and not (src / "tokens.json").is_file():
        print(f"refusing: {src} has no .data or tokens.json; point --from at the v8 folder", file=sys.stderr)
        return 2
    home = settings.home()
    if home is not None and home.resolve() == src:
        print("refusing: the source is this install's own home", file=sys.stderr)
        return 2
    if settings.dev_mode() and not opts.get("force"):
        print("refusing: EDP_HOME is a source checkout (dev mode); import targets an installed home",
              file=sys.stderr)
        return 2
    items = plan(src)
    env = plan_env(src)
    report(src, items, env)
    if not opts.get("apply"):
        print("\ndry run: nothing was written. Re-run with --apply to import.")
        return 0
    if launcher.running("board"):
        print("\nrefusing: this install's board is running; `heronry stop` first", file=sys.stderr)
        return 1
    apply(items, env)
    db = next((it for it in items if it.kind == "db"), None)
    if db is not None:
        print(f"\nimported: {db_counts(db.dst)}")
    print("done. The source was not modified; `heronry start` runs the imported state.")
    return 0
