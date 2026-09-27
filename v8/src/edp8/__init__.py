"""edp8 package."""
from importlib.metadata import PackageNotFoundError, version as _dist_version

try:  # one version for the four packages, the web app and the extension (S9); pyproject is the source
    __version__ = _dist_version("edp8")
except PackageNotFoundError:  # a bare source tree with no install
    __version__ = "0.0.0+source"
