"""Print the REAL opencode.exe path (never the npm .CMD shim) or exit 1.

Used by launch-opencode-neuron.bat. Mirrors edp_pool.opencode_launcher.
resolve_opencode_bin, plus os.path.realpath so an nvm-style SYMLINKED
node dir (C:\\nvm4w\\nodejs -> ...\\nvm\\vX) resolves — cmd's `dir` cannot
traverse that symlink, which is why the .bat cannot do this itself.
EDP_OPENCODE_BIN overrides everything.
"""

import glob
import os
import shutil
import sys

override = os.environ.get("EDP_OPENCODE_BIN", "").strip()
if override:
    print(override)
    sys.exit(0)

which = shutil.which("opencode")
if which:
    real_dir = os.path.realpath(os.path.dirname(which))
    hits = glob.glob(os.path.join(
        real_dir, "node_modules", "opencode-ai", "node_modules",
        "opencode-windows-*", "bin", "opencode.exe"))
    if hits:
        print(sorted(hits)[0])
        sys.exit(0)
    if which.lower().endswith(".exe"):
        print(which)
        sys.exit(0)
sys.exit(1)
