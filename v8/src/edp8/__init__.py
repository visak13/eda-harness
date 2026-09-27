"""edp8 package."""

#: One version for the four packages, the web app and the VS Code extension (S9). A source constant, not
#: package metadata, so a stale editable install never reports an old version; tests/test_version_sync.py
#: keeps it equal to every pyproject.toml and package.json.
__version__ = "0.9.0"
