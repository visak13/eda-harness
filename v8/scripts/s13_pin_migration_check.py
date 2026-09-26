"""S13 c-54afa8a81b: every existing epic in a COPY of the host DB pins standard@1 after migration.

Usage: python scripts/s13_pin_migration_check.py <live edp8.db> <scratch copy path>  (the live DB is opened read-only)."""
import sqlite3, sys
src, dst = sys.argv[1], sys.argv[2]
with sqlite3.connect(f"file:{src}?mode=ro", uri=True) as s, sqlite3.connect(dst) as d:
    s.backup(d)
from edp8.store import Store
from edp8.board import Board
store = Store(dst)
n_epics = store._conn.execute("SELECT count(*) FROM ticket WHERE kind='epic'").fetchone()[0]
had = store._conn.execute("SELECT count(*) FROM sqlite_master WHERE name='workflow_pins'").fetchone()[0]
board = Board(store)  # board open runs WorkflowRegistry.migrate_all()
pins = dict(store._conn.execute("SELECT epic_id, ref FROM workflow_pins").fetchall())
epics = [r[0] for r in store._conn.execute("SELECT id FROM ticket WHERE kind='epic'")]
print(f"copy: {dst}")
print(f"workflow_pins table before open: {'yes' if had else 'no'}")
print(f"epics: {n_epics}; pinned after open: {sum(1 for e in epics if e in pins)}")
print(f"refs: {sorted(set(pins.values()))}")
print(f"every epic pins standard@1: {all(pins.get(e) == 'standard@1' for e in epics)}")
print(f"sample: {[(e, board.workflow_of(e).ref) for e in epics[:3]]}")
