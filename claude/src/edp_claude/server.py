"""Context factory + MCP wiring (LLD §1 server.py).

`make_context` is the single DI point: swap StubPool/StubBroker/FileMemory/
StubFsm for Http* (components #3/#4/#5) HERE and nothing at any call site
changes — the inversion-of-control the whole design rests on.

# TODO(claude-skeleton): the actual MCP transport registration (FastMCP /
# stdio) is not load-bearing for WALK-1 (which drives the tools directly)
# and depends on the MCP SDK choice. Wire it when the first real shell
# needs to reach these tools over MCP.
"""

from pathlib import Path

from .store import (NeuronStore, NorthStarStore, PlanStore, RecipeStore,
                    SpecStore)
from .stubs import FileMemory, StubBroker, StubEmbed, StubFsm, StubPool
from .tools import Ctx, build_registry


def make_context(root: Path) -> Ctx:
    """Stub-backed context (component #2 default; tests, offline).
    Neuron DB lives at .neurons/registry.db; specs at .specs/ (vision
    phases 2+3). StubEmbed keeps discovery deterministic + offline."""
    root = Path(root)
    return Ctx(
        recipes=RecipeStore(root / ".recipes"),
        plans=PlanStore(root / ".plans"),
        pool=StubPool(),
        broker=StubBroker(),
        memory=FileMemory(root / ".memory" / "facts.jsonl"),
        fsm=StubFsm(),
        neurons=NeuronStore(root / ".neurons" / "registry.db"),
        specs=SpecStore(root / ".specs"),
        embed=StubEmbed(),
        north_star=NorthStarStore(root / ".recipes"),
    )


def make_http_context(root: Path, *, broker, pool, embed=None) -> Ctx:
    """Integration context (#9). The ONLY thing that changes vs
    make_context is which Broker/Pool/Embed object is injected — proof
    that the stub→http swap is a DI choice, not a call-site change
    (DESIGN-v4 IoC).

    `broker` must satisfy BrokerPort, `pool` PoolPort (HttpBroker /
    HttpPool duck-type them). `embed` is HttpEmbed (ollama) in prod;
    defaults to StubEmbed so integration without ollama still works.
    FSM stays StubFsm until component #5.
    """
    root = Path(root)
    return Ctx(
        recipes=RecipeStore(root / ".recipes"),
        plans=PlanStore(root / ".plans"),
        pool=pool,
        broker=broker,
        memory=FileMemory(root / ".memory" / "facts.jsonl"),
        fsm=StubFsm(),
        neurons=NeuronStore(root / ".neurons" / "registry.db"),
        specs=SpecStore(root / ".specs"),
        embed=embed or StubEmbed(),
        north_star=NorthStarStore(root / ".recipes"),
    )


def make_registry(root: Path) -> list:
    return build_registry(make_context(root))
