"""Print the newest opencode session id for the given title, or exit 1.
Used by launch-opencode-neuron.bat (avoids cmd for/f quoting traps)."""

import sqlite3
import sys

title = sys.argv[1]
db = sys.argv[2]
row = sqlite3.connect(f"file:{db}?mode=ro", uri=True).execute(
    "select id from session where title=? order by time_created desc "
    "limit 1", (title,)).fetchone()
if not row:
    sys.exit(1)
print(row[0])
