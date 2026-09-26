"""edp8's view of the one settings registry (design-e963c656f5 §4.2): a re-export of
``edp_contracts.settings``. Every path, port and knob edp8 reads comes from here."""
from __future__ import annotations

from edp_contracts.settings import *  # noqa: F403
from edp_contracts.settings import __all__  # noqa: F401
