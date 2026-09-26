"""`heronry workflows …` (S13 s-461403ebd1; S3's cli.py loads `main` lazily, note m-e4ec944e85).

`main(["check", "--db", <path>, "--json"])` runs the §4.14(e).4 update compatibility check on a scratch copy
of the DB (edp8.workflow.check_db; the live DB is never written): stdout is a JSON list of
{workflow, version, ok, errors}; exit 0 all ok, 1 any failure, 2 usage error (steer m-f0835edaca)."""
from __future__ import annotations

from .workflow import workflows_cmd


def main(argv: list[str]) -> int:
    """argv excludes the word `workflows`."""
    return workflows_cmd(list(argv))


if __name__ == "__main__":
    import sys
    raise SystemExit(main(sys.argv[1:]))
