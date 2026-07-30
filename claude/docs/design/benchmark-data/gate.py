"""BENCH-WORKER-CODING acceptance gate. Arm-independent, mechanical.

Usage: python gate.py <workspace_dir>
Prints one JSON object to stdout. Never trusts the arm's own claims.
"""
import hashlib
import importlib
import json
import re
import subprocess
import sys
import tempfile
from pathlib import Path

UNGUARDED = '''def _write_sidecar(root: Path, ref: str, text: str) -> bool:
    write_atomic(root / ref, text)
    return True
'''

FUNC_RE = re.compile(
    r"^def _write_sidecar\(.*?(?=^def |\Z)", re.M | re.S)


def sha(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


def pytest_run(ws: Path):
    r = subprocess.run([sys.executable, "-m", "pytest", "tests", "-q"],
                       cwd=ws, capture_output=True, text=True, timeout=300)
    return r.returncode, (r.stdout + r.stderr)


def golden(ws: Path):
    """Behavioural checks on the ARM's sc/tiering.py. Arm-independent."""
    sys.path.insert(0, str(ws))
    for m in [m for m in list(sys.modules) if m.startswith("sc")]:
        del sys.modules[m]
    t = importlib.import_module("sc.tiering")
    out = {}
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        ref, text = "side/x.txt", "hello world\n" * 40

        # G2: missing sidecar -> must write
        out["G2_missing_writes"] = (t._write_sidecar(root, ref, text) is True
                                    and (root / ref).read_text(encoding="utf-8") == text)

        # G3: unchanged content -> must NOT write (return False AND mtime frozen)
        p = root / ref
        import os
        os.utime(p, (1_000_000, 1_000_000))
        before_m, before_h = p.stat().st_mtime_ns, sha(p)
        rv = t._write_sidecar(root, ref, text)
        out["G3_unchanged_returns_false"] = rv is False
        out["G3_unchanged_no_write"] = (p.stat().st_mtime_ns == before_m
                                        and sha(p) == before_h)

        # G4: changed content -> must write
        text2 = text + "CHANGED\n"
        out["G4_changed_writes"] = (t._write_sidecar(root, ref, text2) is True
                                    and p.read_text(encoding="utf-8") == text2)

        # G5: INVARIANT - digest substitution not gated on the return value.
        #     Dehydrate the same long text twice from a fresh dict each time;
        #     the 2nd save skips the write but MUST still untier the field.
        os.environ["EDP_TIER_WRITE"] = "1"
        long = "L" * 900
        r2 = "side/f.txt"
        o1 = {"description": long}
        t._dehydrate_field(o1, "description", "description_ref", r2, root)
        first_ok = (o1.get("description_ref") == r2
                    and "full text in" in o1["description"]
                    and (root / r2).read_text(encoding="utf-8") == long)
        o2 = {"description": long, "description_ref": r2}   # 2nd save, unchanged
        t._dehydrate_field(o2, "description", "description_ref", r2, root)
        second_ok = ("full text in" in o2["description"]
                     and (root / r2).read_text(encoding="utf-8") == long)
        out["G5_digest_not_gated_on_write"] = bool(first_ok and second_ok)

        # G6: round-trip - hydrate restores full text after a skipped write
        warn = []
        t._hydrate_field(o2, "description", "description_ref", root, warn)
        out["G6_roundtrip_full_text"] = (o2["description"] == long and not warn)
    sys.path.remove(str(ws))
    return out


def main():
    ws = Path(sys.argv[1]).resolve()
    tf = ws / "tests" / "test_sidecar_guard.py"
    src = ws / "sc" / "tiering.py"
    res = {"workspace": str(ws)}

    res["G0_arm_test_exists"] = tf.is_file()
    if not res["G0_arm_test_exists"]:
        res["quality_held"] = False
        res["reason"] = "arm wrote no tests/test_sidecar_guard.py"
        print(json.dumps(res)); return

    rc, log = pytest_run(ws)
    res["G1_arm_suite_green"] = (rc == 0)
    m = re.search(r"(\d+) passed", log)
    res["G1_passed_count"] = int(m.group(1)) if m else 0
    res["G1_tail"] = log.strip().splitlines()[-1] if log.strip() else ""

    try:
        res.update(golden(ws))
    except Exception as e:
        res["golden_error"] = f"{type(e).__name__}: {e}"

    # ---- MUTATION: revert the guard, the arm's own test must go RED ----
    orig = src.read_bytes()
    orig_sha = hashlib.sha256(orig).hexdigest()
    txt = src.read_text(encoding="utf-8")
    if not FUNC_RE.search(txt):
        res["MUT_applied"] = False
        res["MUT_note"] = "could not locate _write_sidecar to mutate"
    else:
        src.write_text(FUNC_RE.sub(UNGUARDED, txt, count=1), encoding="utf-8")
        res["MUT_applied"] = True
        mrc, mlog = pytest_run(ws)
        res["MUT_red"] = (mrc != 0)
        fails = re.findall(r"^(FAILED [^\s]+.*)$", mlog, re.M)
        res["MUT_failing"] = fails[:4]
        asserts = re.findall(r"^E\s+(.*)$", mlog, re.M)
        res["MUT_assertion_text"] = asserts[:4]
        src.write_bytes(orig)
        res["MUT_reverted_byte_identical"] = (hashlib.sha256(src.read_bytes()).hexdigest() == orig_sha)
        rc2, _ = pytest_run(ws)
        res["MUT_green_after_revert"] = (rc2 == 0)

    keys = ["G0_arm_test_exists", "G1_arm_suite_green", "G2_missing_writes",
            "G3_unchanged_returns_false", "G3_unchanged_no_write",
            "G4_changed_writes", "G5_digest_not_gated_on_write",
            "G6_roundtrip_full_text", "MUT_red",
            "MUT_reverted_byte_identical", "MUT_green_after_revert"]
    res["gate_passed"] = all(res.get(k) is True for k in keys[:8])
    res["mutation_proved"] = all(res.get(k) is True for k in keys[8:])
    res["quality_held"] = res["gate_passed"] and res["mutation_proved"]
    res["failed_checks"] = [k for k in keys if res.get(k) is not True]
    print(json.dumps(res, indent=2))


if __name__ == "__main__":
    main()
