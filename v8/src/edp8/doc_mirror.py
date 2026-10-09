"""Read-only docs mirror: every doc is also a file `<agent-home>/docs/<scope>/<id>.md`, so a seat can Read, grep and
sed it. The board writes it in the same step as the database write (Store.put): the temp file is written inside the
transaction (a failure rolls the database back, so neither copy changes) and renamed over the mirror file only after
the commit. Nothing else writes here; edits go through doc_edit. Files are marked read-only, so a native Edit fails."""
import logging
import os
import re
import stat
import time
from pathlib import Path

log = logging.getLogger("edp8.doc_mirror")
_SAFE = re.compile(r"[^A-Za-z0-9._-]+")


def mirror_root(home: str | os.PathLike) -> Path:
    return Path(home) / "docs"


def mirror_path(root: Path, doc) -> Path:
    """`<root>/<scope>/<id>.md`; a scope like `domain:ops` becomes `domain-ops`. Never outside `root`."""
    scope = _SAFE.sub("-", doc.scope or "global").strip(".-") or "global"
    path = (root / scope / f"{_SAFE.sub('-', doc.id).strip('.-')}.md")
    if root.resolve() not in path.resolve().parents:
        raise ValueError(f"mirror path for {doc.id!r} leaves {root}")
    return path


def render(doc) -> str:
    """The doc as a file: a short front matter (what a grep hit needs to find its doc), then the body as stored."""
    head = [f"id: {doc.id}", f"version: {doc.version}", f"type: {getattr(doc.doc_type, 'value', doc.doc_type)}",
            f"scope: {doc.scope}", f"status: {getattr(doc.status, 'value', doc.status)}",
            f"title: {doc.title}"]
    return "---\n" + "\n".join(head) + "\n---\n" + doc.body_md


STAGING = ".staging"  # under the mirror root, outside every scope folder; its files are not .md, so no search finds them


def stage(root: Path, doc) -> tuple[Path, Path]:
    """Write the temp file in `<root>/.staging/` (never beside the mirror files); returns (temp, final). Raises on
    any failure. The temp holds an uncommitted body until the commit: a rollback discards it (Store.after_rollback)."""
    final = mirror_path(root, doc)
    final.parent.mkdir(parents=True, exist_ok=True)
    stage_dir = root / STAGING
    stage_dir.mkdir(parents=True, exist_ok=True)
    tmp = stage_dir / f"{final.parent.name}__{final.stem}.tmp"
    if tmp.exists():
        _writable(tmp)
    try:
        with open(tmp, "w", encoding="utf-8", newline="") as f:
            f.write(render(doc))
            f.flush()
            os.fsync(f.fileno())
    except BaseException:  # a half-staged body never outlives its failed write (the rollback hook is not yet set)
        discard(tmp)
        raise
    return tmp, final


def _read_only(path: Path) -> None:
    try:
        os.chmod(path, stat.S_IREAD | stat.S_IRGRP | stat.S_IROTH)
    except OSError:
        pass


def publish(tmp: Path, final: Path, *, attempts: int = 5, pause: float = 0.05) -> bool:
    """Rename the staged file over the mirror file and make it read-only (after the database commit). A reader that
    holds the old file open makes Windows refuse the replace, so it is retried with a short backoff. True when the
    mirror file is current; False when it is not: the old file is then read-only again and the caller queues the
    doc for repair. The mirror file is never left writable."""
    if not tmp.exists():  # two writes of one doc in one transaction: the first publish already renamed the last
        return True
    err: OSError | None = None
    for n in range(attempts):
        try:
            if final.exists():
                _writable(final)  # Windows will not replace a read-only file
            os.replace(tmp, final)
            _read_only(final)
            return True
        except OSError as e:
            err = e
            if final.exists():
                _read_only(final)
            if n + 1 < attempts:
                time.sleep(pause * (n + 1))
    log.warning("docs mirror: could not publish %s after %d tries (queued for repair): %s", final, attempts, err)
    return False


def discard(tmp: Path) -> None:
    try:
        _writable(tmp)
        tmp.unlink()
    except OSError:
        pass


def _writable(path: Path) -> None:
    try:
        os.chmod(path, stat.S_IWRITE | stat.S_IREAD)
    except OSError:
        pass


def backfill(store, root: Path) -> dict[str, int]:
    """Start-up, once per start: write every doc whose file is missing or differs, drop stale staged files.
    Idempotent, so it doubles as the repair after a file was deleted or edited behind the board's back. A publish
    that did not land counts as `failed` (and queues the doc on the store for the next commit's repair)."""
    done = {"written": 0, "same": 0, "failed": 0}
    for pattern in (f"{STAGING}/*", "*/*.md.tmp"):  # the staging dir, and the temp files of the layout before it
        for tmp in root.glob(pattern) if root.is_dir() else ():
            discard(tmp)
    pending = getattr(store, "mirror_pending", None)
    for doc in store.query("doc", limit=-1):
        try:
            final = mirror_path(root, doc)
            text = render(doc)
            if final.is_file() and final.read_text(encoding="utf-8") == text and not os.access(final, os.W_OK):
                done["same"] += 1
                continue
            if publish(*stage(root, doc)):
                done["written"] += 1
                if pending is not None:
                    pending.discard(doc.id)
            else:
                done["failed"] += 1
                if pending is not None:
                    pending.add(doc.id)
        except Exception as e:  # noqa: BLE001 - one bad doc never blocks the board
            log.warning("docs mirror: backfill of %s failed: %s", getattr(doc, "id", "?"), e)
            done["failed"] += 1
    return done
