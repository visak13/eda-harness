"""Reactive event layer (REACTIVE-STREAMS.md).

The agent composes read-only event sources + RxPY operators via the
`observe()` MCP tool's lambda; the driver compiles that lambda to a
long-running RxPY pipeline and emits NDJSON that a Claude Code `Monitor`
watches (one Monitor per `observe` call). The sink only WAKES the shell
+ delivers the emission — mutation stays in the object/CRUD surface.
"""

from .effects import (
    EffectAllowlistError,
    EffectArgUnresolved,
    EffectDispatcher,
    EffectError,
    EffectMutatingNotOptedIn,
    EffectSpec,
    subscribe_effect,
)
from .handle_index import (
    register_subscription,
    sids_for_handle,
    specs_for_handle,
)
from .registry import (
    RegisteredRule,
    RegistryError,
    RuleExists,
    RuleNotFound,
    RuleRegistry,
    RuleSupervisor,
    SupervisorConfig,
    validate_spec,
)
from .runtime import (
    NEURON_SELF_AUTHOR,
    ROLE_PRIMARY_WAKES,
    ROLE_WAKE_KINDS,
    RxRuntime,
    SpecError,
    author_of,
    compile_spec,
    kind_of,
    wake_kinds,
)

__all__ = [
    "RxRuntime", "SpecError", "compile_spec",
    "ROLE_WAKE_KINDS", "ROLE_PRIMARY_WAKES",
    "NEURON_SELF_AUTHOR", "wake_kinds", "kind_of", "author_of",
    "EffectSpec", "EffectDispatcher", "subscribe_effect",
    "EffectError", "EffectAllowlistError", "EffectMutatingNotOptedIn",
    "EffectArgUnresolved",
    "RuleRegistry", "RuleSupervisor", "SupervisorConfig", "RegisteredRule",
    "RegistryError", "RuleNotFound", "RuleExists", "validate_spec",
    "register_subscription", "sids_for_handle", "specs_for_handle",
]
