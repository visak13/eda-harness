"""Domain registry (DESIGN-v4 §5). software_engineering + generic at launch.

A domain module supplies:
  - kg_filter(fact) -> Verdict      (what is memory-worthy)
  - success_criteria(plan) -> str|None  (terminal_status, per shape×domain)
"""

from dataclasses import dataclass
from importlib import import_module

LAUNCH_DOMAINS = ("software_engineering", "generic")


@dataclass(frozen=True)
class Verdict:
    keep: bool
    reason: str


def _module(domain: str):
    name = domain if domain in LAUNCH_DOMAINS else "generic"
    return import_module(f"{__name__}.{name}")


def kg_filter_for(domain: str):
    return _module(domain).kg_filter


def success_criteria_for(domain: str):
    return _module(domain).success_criteria
