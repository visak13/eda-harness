r"""Deterministic core+company behavior resolver for design-templates-mcp.

This module backs the ADDITIVE ``fetch_behavior(name, framework, layer)`` MCP
tool (registered in :mod:`design_templates_mcp.server`). It implements the
pure lookup + merge of the behavior layer exactly as specified in
``eda-designs/docs/behavior-layer-design.md`` §4 (worked example) and §5
(resolution / merge algorithm), per recipe decision d1.

Design posture (mirrors the existing catalog, audit §3):

- **Pure & side-effect free.** Every step is a path lookup, a file read, or a
  set-union / object-merge — *no generation at serve time*. Same inputs ->
  byte-identical output.
- **Read-only on eda-designs.** Reads live from the same content root the
  server already uses (``catalog.designs_root()`` / ``EDA_DESIGNS_ROOT``);
  never writes there.
- **Instruction-shaped errors, never tracebacks.** All precondition failures
  return the existing ``catalog._err`` envelope shape (unknown name / framework
  / layer, missing files, bad ``extends`` target, non-monotonic patch).
- **Monotonic composition.** ``apply_patch`` may only ADD states / events /
  context keys; any attempt to delete or rebind a core state/transition is a
  hard error — identical semantics to the determinism gate
  ``eda-designs/tools/check-composition.mjs`` (recipe action a7), so a composed
  fetch reproduces that gate's ``composed_machine``.

The two existing tools (``list_templates`` / ``fetch_template_by_name``) are
untouched; this is purely additive.
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

# ---------------------------------------------------------------------------
# Reuse the catalog's content-root resolution and `_err` envelope helper.
# This module lives at the design-templates-mcp root (per the recipe action),
# while the package lives under ``src/``; make the package importable whether
# or not it has been ``pip install -e``'d, then borrow its conventions.
# ---------------------------------------------------------------------------
_SRC = Path(__file__).resolve().parent / "src"
if _SRC.is_dir() and str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from design_templates_mcp.catalog import _err, designs_root  # noqa: E402

FRAMEWORKS: tuple[str, ...] = ("react", "vanilla", "angular")
# ``"custom"`` is the live namespace name (the eda-designs tree was restructured
# in s9: top-level ``company/`` was renamed to ``custom/``). ``"company"`` is kept
# as a DEPRECATED back-compat alias that now reads ``custom/`` so nothing
# downstream snaps. NOTE: per separation-architecture.md §4.3, composition
# (``layer="composed"``) is being moved OUT of the MCP to the consumer side; it
# is kept here only during the transition — new consumers use the per-axis
# ``resolve_behavior_primitive`` + the documented ASSEMBLE contract instead.
LAYERS: tuple[str, ...] = ("core", "custom", "company", "composed")
# Valid namespaces for the per-axis structure primitive (NOT "composed" — §4.3).
NAMESPACES: tuple[str, ...] = ("core", "custom")

# Per-framework core connector filenames (the connect-snippet axis, §1.3).
_CONNECT_FILE: dict[str, str] = {
    "react": "connect.react.tsx",
    "vanilla": "connect.vanilla.js",
    "angular": "connect.angular.ts",
}


# ===========================================================================
# Minimal, dependency-free JS object-literal reader.
#
# `machine.js` / `machine.patch.js` export plain-data object literals (XState
# notation borrowed without its runtime). We need their data — states, events,
# context keys — to perform the monotonic merge. We deliberately DROP
# function-valued entries (arrow guards like `canResize: (ctx) => ...`), which
# is exactly what the reference node gate does implicitly when it
# `JSON.stringify`s the imported machine (functions serialise to nothing). So a
# composed machine produced here matches the gate's `composed_machine` JSON.
#
# This is a tolerant reader for the constrained literal grammar these authored
# files use (objects, arrays, strings, numbers, true/false/null, unquoted
# identifier keys, // and /* */ comments, trailing commas, and arrow/function
# values which are skipped). It is NOT a general JS evaluator.
# ===========================================================================
class _JsParseError(ValueError):
    """Raised when a behavior JS module cannot be read as a data literal."""


_DROP = object()  # sentinel for a function-valued entry we intentionally omit


class _LiteralReader:
    def __init__(self, text: str) -> None:
        self.s = text
        self.i = 0
        self.n = len(text)

    # -- whitespace + comments -------------------------------------------
    def _skip_ws(self) -> None:
        while self.i < self.n:
            c = self.s[self.i]
            if c in " \t\r\n":
                self.i += 1
            elif c == "/" and self.i + 1 < self.n and self.s[self.i + 1] == "/":
                self.i += 2
                while self.i < self.n and self.s[self.i] != "\n":
                    self.i += 1
            elif c == "/" and self.i + 1 < self.n and self.s[self.i + 1] == "*":
                self.i += 2
                while self.i + 1 < self.n and not (
                    self.s[self.i] == "*" and self.s[self.i + 1] == "/"
                ):
                    self.i += 1
                self.i += 2
            else:
                break

    # -- value dispatch ---------------------------------------------------
    def read_value(self):
        self._skip_ws()
        if self.i >= self.n:
            raise _JsParseError("unexpected end of input")
        c = self.s[self.i]
        if c == "{":
            return self._read_object()
        if c == "[":
            return self._read_array()
        if c in "\"'":
            return self._read_string()
        if c == "(" or self.s.startswith("function", self.i):
            return self._read_function()  # arrow / function expr -> _DROP
        return self._read_bareword()

    def _read_object(self) -> dict:
        obj: dict = {}
        self.i += 1  # consume '{'
        while True:
            self._skip_ws()
            if self.i >= self.n:
                raise _JsParseError("unterminated object")
            if self.s[self.i] == "}":
                self.i += 1
                return obj
            key = self._read_key()
            self._skip_ws()
            if self.i >= self.n or self.s[self.i] != ":":
                raise _JsParseError(f"expected ':' after key {key!r}")
            self.i += 1  # consume ':'
            value = self.read_value()
            if value is not _DROP:
                obj[key] = value
            self._skip_ws()
            if self.i < self.n and self.s[self.i] == ",":
                self.i += 1
            # loop; '}' handled at top

    def _read_array(self) -> list:
        arr: list = []
        self.i += 1  # consume '['
        while True:
            self._skip_ws()
            if self.i >= self.n:
                raise _JsParseError("unterminated array")
            if self.s[self.i] == "]":
                self.i += 1
                return arr
            value = self.read_value()
            if value is not _DROP:
                arr.append(value)
            self._skip_ws()
            if self.i < self.n and self.s[self.i] == ",":
                self.i += 1

    def _read_key(self) -> str:
        self._skip_ws()
        c = self.s[self.i]
        if c in "\"'":
            return self._read_string()
        start = self.i
        while self.i < self.n and (self.s[self.i].isalnum() or self.s[self.i] in "_$"):
            self.i += 1
        if self.i == start:
            raise _JsParseError(f"expected object key at offset {self.i}")
        return self.s[start:self.i]

    def _read_string(self) -> str:
        quote = self.s[self.i]
        self.i += 1
        out: list[str] = []
        while self.i < self.n:
            c = self.s[self.i]
            if c == "\\":
                nxt = self.s[self.i + 1] if self.i + 1 < self.n else ""
                out.append({"n": "\n", "t": "\t", "r": "\r"}.get(nxt, nxt))
                self.i += 2
                continue
            if c == quote:
                self.i += 1
                return "".join(out)
            out.append(c)
            self.i += 1
        raise _JsParseError("unterminated string")

    def _read_function(self):
        """Consume an arrow or `function` value at the current position -> _DROP.

        Handles `(args) => expr`, `(args) => { ... }`, and `function (...) {...}`.
        We never need the body, only to skip past it cleanly so the surrounding
        object/array parse continues. Mirrors JSON.stringify dropping functions.
        """
        # Skip a leading `function` keyword if present.
        if self.s.startswith("function", self.i):
            self.i += len("function")
            self._skip_ws()
        # Skip the parameter parenthesis group if present.
        if self.i < self.n and self.s[self.i] == "(":
            self.i = self._skip_balanced("(", ")")
        self._skip_ws()
        # Arrow body.
        if self.s.startswith("=>", self.i):
            self.i += 2
            self._skip_ws()
            if self.i < self.n and self.s[self.i] == "{":
                self.i = self._skip_balanced("{", "}")
            else:
                self._skip_expression()
        elif self.i < self.n and self.s[self.i] == "{":
            # `function (...) { ... }`
            self.i = self._skip_balanced("{", "}")
        return _DROP

    def _skip_balanced(self, open_ch: str, close_ch: str) -> int:
        depth = 0
        i = self.i
        while i < self.n:
            c = self.s[i]
            if c in "\"'":
                self.i = i
                self._read_string()
                i = self.i
                continue
            if c == open_ch:
                depth += 1
            elif c == close_ch:
                depth -= 1
                if depth == 0:
                    return i + 1
            i += 1
        raise _JsParseError(f"unbalanced {open_ch}{close_ch}")

    def _skip_expression(self) -> None:
        """Skip a bare expression up to a top-level ',' or '}' or ']'."""
        depth = 0
        while self.i < self.n:
            c = self.s[self.i]
            if c in "\"'":
                self._read_string()
                continue
            if c in "([{":
                depth += 1
            elif c in ")]}":
                if depth == 0:
                    return
                depth -= 1
            elif c == "," and depth == 0:
                return
            self.i += 1

    def _read_bareword(self):
        start = self.i
        while self.i < self.n and self.s[self.i] not in ",}]: \t\r\n":
            self.i += 1
        token = self.s[start:self.i].strip()
        if token == "true":
            return True
        if token == "false":
            return False
        if token in ("null", "undefined"):
            return None
        try:
            return int(token)
        except ValueError:
            pass
        try:
            return float(token)
        except ValueError:
            pass
        raise _JsParseError(f"unrecognised token {token!r}")


def _extract_object_literal(text: str, ident: str) -> dict:
    """Parse the object literal assigned to ``export const <ident> = { ... }``.

    Returns the literal as a Python dict (function-valued entries dropped).
    Raises :class:`_JsParseError` if the binding or a parseable literal is
    not found.
    """
    needle = f"const {ident}"
    pos = text.find(needle)
    if pos == -1:
        raise _JsParseError(f"binding 'const {ident}' not found")
    eq = text.find("=", pos + len(needle))
    if eq == -1:
        raise _JsParseError(f"no '=' after 'const {ident}'")
    reader = _LiteralReader(text)
    reader.i = eq + 1
    value = reader.read_value()
    if not isinstance(value, dict):
        raise _JsParseError(f"'{ident}' is not an object literal")
    return value


# ===========================================================================
# File helpers
# ===========================================================================
def _read_file(root: Path, rel: str) -> dict | None:
    """Read one backing file; return ``{path, bytes, content}`` or ``None``.

    ``rel`` is a POSIX-style relative path under the content root, matching the
    identifiers the existing catalog emits.
    """
    p = root / rel
    if not p.is_file():
        return None
    text = p.read_text(encoding="utf-8")
    return {"path": rel, "bytes": len(text.encode("utf-8")), "content": text}


def _registry_config_defaults(registry: dict) -> dict:
    """Flatten a registry.json ``config`` block to ``{key: default}``.

    Core config is shaped ``{"scrollable": {"type": ..., "default": true}}``;
    we project it to plain ``{"scrollable": true}`` (the machine context shape).
    """
    out: dict = {}
    for key, spec in (registry.get("config") or {}).items():
        if isinstance(spec, dict) and "default" in spec:
            out[key] = spec["default"]
        else:
            out[key] = spec
    return out


# ===========================================================================
# Monotonic patch merge — identical contract to tools/check-composition.mjs.
# ===========================================================================
def apply_patch(core_machine: dict, patch: dict) -> tuple[dict, list[str]]:
    """Apply the company ``patch`` onto the ``core_machine`` (additive only).

    Returns ``(composed, violations)``. ``core_machine`` is never mutated. A
    non-empty ``violations`` list means the patch tried to delete or rebind a
    core state / transition / context key (the monotonic rule, §4.2).
    """
    composed = json.loads(json.dumps(core_machine))  # deep copy; core read-only
    composed.setdefault("context", {})
    composed.setdefault("states", {})
    violations: list[str] = []

    core_context = core_machine.get("context", {})
    core_states = core_machine.get("states", {})

    # context: additive new keys only.
    for key, val in (patch.get("context") or {}).items():
        if key in core_context:
            violations.append(f'context key "{key}" already exists in core (rebind refused)')
            continue
        composed["context"][key] = val

    # addStates: brand-new states only.
    for name, node in (patch.get("addStates") or {}).items():
        if name in core_states:
            violations.append(f'addStates tried to redefine existing core state "{name}" (refused)')
            continue
        composed["states"][name] = json.loads(json.dumps(node))

    # amendStates: may only ADD new event keys to an existing state's `on` map.
    for name, amend in (patch.get("amendStates") or {}).items():
        if name not in core_states:
            violations.append(f'amendStates referenced unknown state "{name}" (refused)')
            continue
        amend_on = (amend or {}).get("on") or {}
        composed["states"][name].setdefault("on", {})
        core_on = core_states[name].get("on") or {}
        for evt, target in amend_on.items():
            if evt in core_on:
                violations.append(
                    f'amendStates rebound existing core event "{evt}" on state "{name}" (refused)'
                )
                continue
            composed["states"][name]["on"][evt] = target

    return composed, violations


# ===========================================================================
# The resolver
# ===========================================================================
def resolve_behavior(
    name: str,
    framework: str,
    layer: str = "composed",
    root: Path | None = None,
) -> dict:
    """Deterministically resolve a behavior's layered content.

    Args:
        name: behavior name, e.g. ``"dialog"`` (a directory under
            ``core/behaviors/``).
        framework: connector axis — ``"react" | "vanilla" | "angular"``.
        layer: ``"core"`` (pristine core only), ``"custom"`` (custom deltas as
            authored; ``"company"`` is a DEPRECATED alias for the same), or
            ``"composed"`` (monotonic core+custom merge, default — deprecated in
            favour of consumer-side ASSEMBLE, §4.3, but kept during transition).

    Returns a JSON-serialisable dict. On any precondition failure returns the
    catalog ``_err`` instruction-shaped envelope (never raises to the boundary).
    """
    root = root or designs_root()
    if not root.is_dir():
        return _err(
            f"designs root not found or not a directory: {root}",
            "Set EDA_DESIGNS_ROOT to the eda-designs checkout, or create it.",
            root=str(root),
        )
    if framework not in FRAMEWORKS:
        return _err(
            f"unknown framework: {framework!r}",
            f"Use one of: {', '.join(FRAMEWORKS)}.",
            valid_frameworks=list(FRAMEWORKS),
        )
    if layer not in LAYERS:
        return _err(
            f"unknown layer: {layer!r}",
            f"Use one of: {', '.join(LAYERS)}.",
            valid_layers=list(LAYERS),
        )

    core_dir_rel = f"core/behaviors/{name}"
    core_reg_rel = f"{core_dir_rel}/registry.json"
    core_reg_file = root / core_reg_rel
    if not core_reg_file.is_file():
        return _err(
            f"no core behavior named {name!r}",
            "Behaviors live under core/behaviors/<name>/registry.json. Check the name.",
            requested=name,
            expected_path=core_reg_rel,
        )

    if layer in ("company", "custom"):
        # "company" is the DEPRECATED alias; both now read the restructured custom/ tree.
        return _read_custom(root, name)
    if layer == "core":
        return _read_core(root, name, framework)
    return _compose(root, name, framework)


def _read_core(root: Path, name: str, framework: str) -> dict:
    """layer="core": pristine core machine + runtime + requested connector + parts + css."""
    core_dir = f"core/behaviors/{name}"
    registry = json.loads((root / f"{core_dir}/registry.json").read_text(encoding="utf-8"))

    connect_rel = f"{core_dir}/{_CONNECT_FILE[framework]}"
    wanted = {
        "runtime": "core/runtime/machine-runtime.js",
        "machine": f"{core_dir}/machine.js",
        "connect": connect_rel,
        "parts": f"{core_dir}/parts.md",
        "css": f"core/design/{name}.css",
    }
    files: dict[str, dict] = {}
    for slot, rel in wanted.items():
        f = _read_file(root, rel)
        if f is None:
            return _err(
                f"core behavior {name!r} is missing a backing file: {rel}",
                "The core registry references a file that is not on disk.",
                name=name,
                framework=framework,
                missing_file=rel,
            )
        files[slot] = f

    contract = registry.get("contract", {})
    return {
        "ok": True,
        "name": name,
        "framework": framework,
        "layer": "core",
        "root": str(root),
        "extends": registry.get("extends"),
        "registry": registry,
        "config": _registry_config_defaults(registry),
        "contract": {
            "part": list(contract.get("part", [])),
            "dataState": list(contract.get("dataState", [])),
        },
        "runtime": files["runtime"],
        "machine": files["machine"],
        "connect": {"framework": framework, **files["connect"]},
        "parts": files["parts"],
        "css": [files["css"]],
        "files": [files[s]["path"] for s in ("runtime", "machine", "connect", "parts", "css")],
    }


def _read_custom(root: Path, name: str) -> dict:
    """layer="custom" (a.k.a. deprecated "company"): the custom deltas exactly as
    authored (no merge). Reads the restructured ``custom/`` tree (s9 rename of the
    former top-level ``company/``)."""
    custom_dir = f"custom/behaviors/{name}"
    reg_file = root / f"{custom_dir}/registry.json"
    if not reg_file.is_file():
        return _err(
            f"no custom extension for behavior {name!r}",
            "A custom layer is optional; this behavior has no custom/behaviors/<name>/.",
            name=name,
            expected_path=f"{custom_dir}/registry.json",
        )
    registry = json.loads(reg_file.read_text(encoding="utf-8"))

    deltas: dict[str, dict] = {}
    optional_slots = {
        "machine_patch": f"{custom_dir}/machine.patch.js",
        "config_defaults": f"{custom_dir}/config.defaults.json",
        "parts_extend": f"{custom_dir}/parts.extend.md",
        "css": f"custom/design/{name}.css",
    }
    for slot, rel in optional_slots.items():
        f = _read_file(root, rel)
        if f is not None:
            deltas[slot] = f

    contract = registry.get("contract", {})
    config_defaults = {}
    if "config_defaults" in deltas:
        config_defaults = json.loads(deltas["config_defaults"]["content"])
        config_defaults = {k: v for k, v in config_defaults.items() if not k.startswith("_")}

    return {
        "ok": True,
        "name": name,
        # canonical layer name post-restructure; "company" stays accepted on input
        # as a deprecated alias but the resolved tree is custom/.
        "layer": "custom",
        "root": str(root),
        "extends": registry.get("extends"),
        "registry": registry,
        "config_defaults": config_defaults,
        "contract": {
            "part": list(contract.get("part", [])),
            "dataState": list(contract.get("dataState", [])),
        },
        "deltas": {slot: f for slot, f in deltas.items()},
        "files": [f["path"] for f in deltas.values()],
    }


def _compose(root: Path, name: str, framework: str) -> dict:
    """layer="composed": deterministic monotonic merge of core + custom (§4.2).

    DEPRECATED (separation-architecture.md §4.3): composition is moving OUT of the
    MCP to the consumer-side ASSEMBLE contract. Kept working during the transition
    so nothing downstream snaps; reads the restructured ``custom/`` tree.
    """
    base = _read_core(root, name, framework)
    if not base.get("ok"):
        return base  # propagate the core error envelope

    custom_dir = f"custom/behaviors/{name}"
    custom_reg_file = root / f"{custom_dir}/registry.json"

    # 4b — no custom layer, or custom declares no extension: core is the answer.
    if not custom_reg_file.is_file():
        base["layer"] = "composed"
        base["composed_from"] = ["core"]
        base["note"] = "no custom extension present; composed == pristine core"
        return base
    custom_registry = json.loads(custom_reg_file.read_text(encoding="utf-8"))
    extends = custom_registry.get("extends")
    if not extends:
        base["layer"] = "composed"
        base["composed_from"] = ["core"]
        base["note"] = "custom registry declares no 'extends'; composed == pristine core"
        return base

    # 4c — the extension target must point at exactly this core behavior.
    expected_extends = f"core/behaviors/{name}"
    if extends != expected_extends:
        return _err(
            f"custom registry for {name!r} extends {extends!r}, expected {expected_extends!r}",
            "custom/behaviors/<name>/registry.json must declare extends == core/behaviors/<name>.",
            name=name,
            declared_extends=extends,
            expected_extends=expected_extends,
        )

    custom = _read_custom(root, name)
    if not custom.get("ok"):
        return custom

    # 4d — MERGE (additive only) ------------------------------------------
    # config: { ...core.config, ...custom.config.defaults } — custom VALUE wins.
    composed_config = {**base["config"], **custom.get("config_defaults", {})}

    # machine: applyPatch(core.machine, custom.machine.patch.js) — monotonic.
    try:
        core_machine = _extract_object_literal(base["machine"]["content"], "dialogMachine")
        patch_text = custom["deltas"].get("machine_patch", {}).get("content")
        patch_obj: dict = {}
        if patch_text is not None:
            patch_obj = _extract_object_literal(patch_text, "patch")
    except _JsParseError as exc:
        return _err(
            f"could not read behavior machine data for {name!r}: {exc}",
            "The core machine.js or custom machine.patch.js is not a parseable data literal.",
            name=name,
        )
    composed_machine, violations = apply_patch(core_machine, patch_obj)
    if violations:
        return _err(
            f"custom patch for {name!r} is not additive (monotonic rule violated)",
            "machine.patch.js may only ADD states/events/context keys; it may not delete or rebind core.",
            name=name,
            violations=violations,
        )

    # parts: core ∪ custom (union, core first, dedup preserving order).
    composed_parts = _union(base["contract"]["part"], custom["contract"]["part"])
    composed_data_state = _union(base["contract"]["dataState"], custom["contract"]["dataState"])

    # connect: custom connector if present, else core (wrap, never edit core).
    connect = base["connect"]
    custom_connect = _read_file(root, f"{custom_dir}/{_CONNECT_FILE[framework]}")
    if custom_connect is not None:
        connect = {"framework": framework, "source_layer": "custom", **custom_connect}
    else:
        connect = {**connect, "source_layer": "core"}

    # css: [ core/design/<name>.css , custom/design/<name>.css ] (core first).
    css = list(base["css"])
    if "css" in custom["deltas"]:
        css.append(custom["deltas"]["css"])

    # Monotonic-merge evidence (the same guarantees the a7 gate asserts).
    core_state_names = list(core_machine.get("states", {}).keys())
    core_ctx_keys = list(core_machine.get("context", {}).keys())
    composed_state_names = list(composed_machine.get("states", {}).keys())
    merge_check = {
        "core_states_present": all(s in composed_machine["states"] for s in core_state_names),
        "core_context_keys_present": all(
            k in composed_machine["context"] for k in core_ctx_keys
        ),
        "core_state_names": core_state_names,
        "added_states": [s for s in composed_state_names if s not in core_state_names],
        "added_context_keys": [
            k for k in composed_machine["context"] if k not in core_ctx_keys
        ],
        "patch_violations": violations,
        "additive_only": not violations,
    }

    return {
        "ok": True,
        "name": name,
        "framework": framework,
        "layer": "composed",
        "root": str(root),
        "composed_from": ["core", "custom"],
        "extends": expected_extends,
        "core_registry": base["registry"],
        "custom_registry": custom_registry,
        # deprecated back-compat alias (former key name pre-s9 restructure):
        "company_registry": custom_registry,
        "config": composed_config,
        "contract": {"part": composed_parts, "dataState": composed_data_state},
        "machine": {
            "composed": composed_machine,
            "layers": [base["machine"], custom["deltas"].get("machine_patch")],
        },
        "runtime": base["runtime"],
        "connect": connect,
        "parts": [base["parts"], custom["deltas"].get("parts_extend")],
        "css": css,
        "merge_check": merge_check,
        "files": [
            base["runtime"]["path"],
            base["machine"]["path"],
            *([custom["deltas"]["machine_patch"]["path"]] if "machine_patch" in custom["deltas"] else []),
            connect["path"],
            *[c["path"] for c in css],
        ],
    }


def _union(a: list, b: list) -> list:
    """Order-preserving set union: all of ``a`` (core), then new items from ``b``."""
    out = list(a)
    for item in b:
        if item not in out:
            out.append(item)
    return out


# ===========================================================================
# Per-axis STRUCTURE/INTERACTION primitive (separation-architecture.md §4.1).
#
# ``resolve_behavior_primitive`` is the structure half of the per-axis cube: it
# returns the FSM + connector + parts + contract for ONE namespace only — NO
# merge, NO composition at serve time (composition is now the consumer's job per
# the ASSEMBLE contract, §4.2/§4.3). Pure deterministic file lookup: same request
# -> byte-identical output.
#
# It carries a ``designHooks`` field with the behavior's TOKEN-ONLY design CSS
# (var(--...) refs, never hardcoded colors) for this behavior+namespace — the
# styling seam the consumer mounts in ASSEMBLE step 5d. The machine/connector
# themselves stay strictly color-free (DESIGN NOTE, planner decision flagged to
# neuron: §4.1 lists no css on the behavior primitive, but §4.2 step 5d mounts
# per-behavior design CSS and only the behavior carries the behavior name — so the
# per-behavior token-only design hook rides with fetch_behavior as a SEPARATE
# field rather than living on the theme primitive).
# ===========================================================================
def resolve_behavior_primitive(
    name: str,
    namespace: str = "core",
    framework: str = "react",
    root: Path | None = None,
) -> dict:
    """Resolve the per-axis STRUCTURE primitive for ONE namespace (no composition).

    Args:
        name: behavior name, e.g. ``"dialog"``.
        namespace: ``"core"`` (the pristine core structure) or ``"custom"`` (the
            additive custom delta only). NOT ``"composed"`` — composition is the
            consumer's job (§4.3).
        framework: connector axis — ``"react" | "vanilla" | "angular"``.

    Returns a JSON-serialisable dict. On any precondition failure returns the
    catalog ``_err`` instruction-shaped envelope (never raises to the boundary).
    """
    root = root or designs_root()
    if not root.is_dir():
        return _err(
            f"designs root not found or not a directory: {root}",
            "Set EDA_DESIGNS_ROOT to the eda-designs checkout, or create it.",
            root=str(root),
        )
    if framework not in FRAMEWORKS:
        return _err(
            f"unknown framework: {framework!r}",
            f"Use one of: {', '.join(FRAMEWORKS)}.",
            valid_frameworks=list(FRAMEWORKS),
        )
    if namespace not in NAMESPACES:
        return _err(
            f"unknown namespace: {namespace!r}",
            "Use 'core' or 'custom'. 'composed' is NOT a primitive namespace — "
            "composition is the consumer's job (see docs/assemble-contract.md, §4.3).",
            valid_namespaces=list(NAMESPACES),
        )
    if namespace == "core":
        return _primitive_core(root, name, framework)
    return _primitive_custom(root, name, framework)


def _primitive_core(root: Path, name: str, framework: str) -> dict:
    """namespace="core": pristine core structure primitive (no merge)."""
    core_dir = f"core/behaviors/{name}"
    reg_file = root / f"{core_dir}/registry.json"
    if not reg_file.is_file():
        return _err(
            f"no core behavior named {name!r}",
            "Behaviors live under core/behaviors/<name>/registry.json. Check the name.",
            requested=name,
            namespace="core",
            expected_path=f"{core_dir}/registry.json",
        )
    registry = json.loads(reg_file.read_text(encoding="utf-8"))

    # Required backing files for the core structure primitive.
    required = {
        "runtime": "core/runtime/machine-runtime.js",
        "machine": f"{core_dir}/machine.js",
        "connect": f"{core_dir}/{_CONNECT_FILE[framework]}",
        "parts": f"{core_dir}/parts.md",
    }
    files: dict[str, dict] = {}
    for slot, rel in required.items():
        f = _read_file(root, rel)
        if f is None:
            return _err(
                f"core behavior {name!r} is missing a backing file: {rel}",
                "The core registry references a file that is not on disk.",
                name=name,
                namespace="core",
                framework=framework,
                missing_file=rel,
            )
        files[slot] = f

    # designHooks: the behavior's TOKEN-ONLY core design CSS (ASSEMBLE step 5d).
    design = _read_file(root, f"core/design/{name}.css")

    contract = registry.get("contract", {})
    return {
        "ok": True,
        "name": name,
        "namespace": "core",
        "framework": framework,
        "root": str(root),
        "extends": registry.get("extends"),
        "registry": registry,
        "config": _registry_config_defaults(registry),
        "contract": {
            "part": list(contract.get("part", [])),
            "dataState": list(contract.get("dataState", [])),
        },
        "runtime": files["runtime"],
        "machine": files["machine"],
        "connect": {"framework": framework, "source_namespace": "core", **files["connect"]},
        "parts": files["parts"],
        "designHooks": [design] if design else [],
        "files": [
            files["runtime"]["path"],
            files["machine"]["path"],
            files["connect"]["path"],
            files["parts"]["path"],
            *([design["path"]] if design else []),
        ],
    }


def _primitive_custom(root: Path, name: str, framework: str) -> dict:
    """namespace="custom": the additive custom STRUCTURE delta only (no merge)."""
    custom_dir = f"custom/behaviors/{name}"
    reg_file = root / f"{custom_dir}/registry.json"
    if not reg_file.is_file():
        return _err(
            f"no custom extension for behavior {name!r}",
            "A custom layer is optional; this behavior has no custom/behaviors/<name>/.",
            name=name,
            namespace="custom",
            expected_path=f"{custom_dir}/registry.json",
        )
    registry = json.loads(reg_file.read_text(encoding="utf-8"))

    # The custom machine delta (additive patch) is the defining file of the layer.
    machine = _read_file(root, f"{custom_dir}/machine.patch.js")
    if machine is None:
        return _err(
            f"custom extension for {name!r} is missing its machine delta",
            "custom/behaviors/<name>/machine.patch.js (the additive delta) is required.",
            name=name,
            namespace="custom",
            missing_file=f"{custom_dir}/machine.patch.js",
        )

    # The neutral runtime is shared (always core/runtime); custom never re-ships it.
    runtime = _read_file(root, "core/runtime/machine-runtime.js")
    if runtime is None:
        return _err(
            f"the neutral machine runtime is missing for {name!r}",
            "core/runtime/machine-runtime.js must be on disk.",
            name=name,
            namespace="custom",
            missing_file="core/runtime/machine-runtime.js",
        )

    # connect.<framework>: custom connector if present, else fall back to core's
    # (color-free either way). Core connector must exist for the requested framework.
    connect_file = _read_file(root, f"{custom_dir}/{_CONNECT_FILE[framework]}")
    connect_ns = "custom"
    if connect_file is None:
        connect_file = _read_file(root, f"core/behaviors/{name}/{_CONNECT_FILE[framework]}")
        connect_ns = "core"
        if connect_file is None:
            return _err(
                f"no {framework!r} connector for behavior {name!r}",
                "Neither custom/ nor core/ ships a connector for this framework.",
                name=name,
                namespace="custom",
                framework=framework,
                missing_file=f"core/behaviors/{name}/{_CONNECT_FILE[framework]}",
            )

    # parts.extend.md (the additive parts delta) — optional.
    parts = _read_file(root, f"{custom_dir}/parts.extend.md")
    # designHooks: the behavior's TOKEN-ONLY custom design CSS (ASSEMBLE step 5d).
    design = _read_file(root, f"custom/design/{name}.css")

    contract = registry.get("contract", {})
    return {
        "ok": True,
        "name": name,
        "namespace": "custom",
        "framework": framework,
        "root": str(root),
        "extends": registry.get("extends"),
        "registry": registry,
        "config": _registry_config_defaults(registry),
        "contract": {
            "part": list(contract.get("part", [])),
            "dataState": list(contract.get("dataState", [])),
        },
        "runtime": runtime,
        "machine": machine,  # the additive delta (machine.patch.js)
        "connect": {"framework": framework, "source_namespace": connect_ns, **connect_file},
        "parts": parts,  # parts.extend.md (may be None if the custom layer adds no parts)
        "designHooks": [design] if design else [],
        "files": [
            runtime["path"],
            machine["path"],
            connect_file["path"],
            *([parts["path"]] if parts else []),
            *([design["path"]] if design else []),
        ],
    }
