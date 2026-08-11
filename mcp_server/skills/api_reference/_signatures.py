"""Parse OpenStudio SWIG Python wrappers into method signatures.

The Ruby bindings are compiled C with no introspectable source, and dir()/getattr()
on the live ``openstudio.model`` module recovers method *names* only — not parameter
names or return types. But SWIG also emits Python proxy files (``openstudio*.py``) that
carry the full class tree and parameter names. We read those as text (never execute
them), then ``search_api`` decorates its output with them.

**The wrappers carry almost no return types.** Zero of the 57,516 class-body methods
declare a ``->`` annotation; only module-level ``Class.method = _fn`` assignments do,
covering ~2,876 methods across exactly four classes (``Model``, ``IdfObject``,
``IdfExtensibleGroup``, ``GltfForwardTranslator``). Those four matter and cannot come
from anywhere else — they are SWIG-synthesized and declared in no header — so this
module still parses them.

Every other class takes its return type from the SDK's C++ headers via ``_headers``,
which state it exactly. See that module for why. When neither source knows, the type is
reported as ``"?"`` rather than guessed: a wrong type is worse than an admitted unknown,
since ``.get`` on a plain Float raises while omitting it on an Optional silently yields
the wrapper.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

from ._headers import header_types, map_cpp_type

# SWIG internal classes to skip
SKIP_CLASSES = {"SwigPyIterator", "_SwigNonDynamicMeta"}

_CLASS_RE = re.compile(r"^class (\w+)\((\w+(?:\.\w+)?)\):")
_METHOD_RE = re.compile(r"^\s{4}def (\w+)\(([^)]*)\)(?:\s*->\s*([\w.]+))?\s*:")
_MODFUNC_RE = re.compile(r"^def (_\w+)\(([^)]*)\)\s*(?:->\s*([\w.]+))?\s*:")
_ASSIGN_RE = re.compile(r"^(?:\w+\.)*(\w+)\.(\w+)\s*=\s*(_\w+)\s*$")
_STATIC_RE = re.compile(r"^\s+@staticmethod")

_SKIP_METHODS = {"__init__", "__repr__", "__str__", "__del__"}

_PRIMITIVE_TYPES = {
    "str": "String",
    "String": "String",
    "bool": "Boolean",
    "int": "Integer",
    "float": "Float",
    "double": "Float",
}

# Module-level cache (built once per process). PLW0603 is allowed in mcp_server.
_cache: dict[str, dict[str, dict]] | None = None


@dataclass
class ParsedMethod:
    name: str
    params: list[str]
    return_type: str | None


@dataclass
class ParsedClass:
    name: str
    instance_methods: dict[str, ParsedMethod] = field(default_factory=dict)
    static_methods: dict[str, ParsedMethod] = field(default_factory=dict)


def _clean_params(raw: str) -> list[str]:
    """Strip self/defaults/annotations, lowercase a leading capital.

    SWIG renders overloaded methods (a setter with several C++ signatures) as
    ``(self, *args)``, losing the real names. We keep that as ``...`` rather than an
    empty list so the rendered signature signals "takes arguments, names unavailable"
    instead of falsely reading as a no-arg call.
    """
    params = []
    for raw_part in raw.split(","):
        part = raw_part.strip()
        if not part or part == "self":
            continue
        if part.startswith("*"):
            if "..." not in params:
                params.append("...")
            continue
        name = re.split(r"[=:]", part)[0].strip().replace("[", "").replace("]", "")
        if name and name[0].isupper():
            name = name[0].lower() + name[1:]
        if name:
            params.append(name)
    return params


def _last_segment(type_str: str | None) -> str | None:
    return type_str.split(".")[-1] if type_str else None


def _parse_module_level_types(path: Path) -> dict[str, dict[str, ParsedMethod]]:
    """Capture ``def _fn(self, x) -> Ret:`` and cross-file ``Class.method = _fn``."""
    func_info: dict[str, ParsedMethod] = {}
    class_methods: dict[str, dict[str, ParsedMethod]] = {}

    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        func_match = _MODFUNC_RE.match(line)
        if func_match:
            func_info[func_match.group(1)] = ParsedMethod(
                name=func_match.group(1),
                params=_clean_params(func_match.group(2)),
                return_type=_last_segment(func_match.group(3)),
            )
            continue
        assign_match = _ASSIGN_RE.match(line)
        if assign_match:
            target_class, method_name, func_name = assign_match.groups()
            info = func_info.get(func_name)
            if info is None:
                continue
            class_methods.setdefault(target_class, {})[method_name] = ParsedMethod(
                name=method_name,
                params=info.params,
                return_type=info.return_type,
            )
    return class_methods


def _parse_python_file(path: Path) -> list[ParsedClass]:
    """Capture ``class X(Parent):`` and its 4-space-indented method definitions."""
    classes: list[ParsedClass] = []
    current: ParsedClass | None = None
    in_static = False

    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        class_match = _CLASS_RE.match(line)
        if class_match:
            name, parent = class_match.group(1), class_match.group(2)
            # Skip SWIG internals / STL container wrapper types / Python-only lowercase
            # classes. *Vector/Optional*/*Set/*Map with parent `object` are SWIG wrappers
            # around std::vector/optional/set/map — collection plumbing, not domain API,
            # and their Python dict/set helper methods (add/iteritems/has_key/...) have no
            # Ruby equivalent. Real domain classes inherit a model parent, never `object`,
            # so this never catches them. current=None so a skipped body can't leak onto
            # the prior class.
            if (
                name in SKIP_CLASSES
                or (name.endswith(("Vector", "Set", "Map")) and parent == "object")
                or (name.startswith("Optional") and parent == "object")
                or name[0].islower()
            ):
                current = None
                in_static = False
                continue
            current = ParsedClass(name=name)
            classes.append(current)
            in_static = False
            continue

        if current is None:
            continue

        if _STATIC_RE.match(line):
            in_static = True
            continue

        method_match = _METHOD_RE.match(line)
        if not method_match:
            continue

        method_name = method_match.group(1)
        if method_name.startswith("_") or method_name in _SKIP_METHODS:
            in_static = False
            continue

        method = ParsedMethod(
            name=method_name,
            params=_clean_params(method_match.group(2)),
            return_type=_last_segment(method_match.group(3)),
        )
        if in_static:
            current.static_methods[method_name] = method
        else:
            current.instance_methods[method_name] = method
        in_static = False

    return classes


def _resolve_return_type(type_str: str | None, all_class_names: set[str]) -> str:
    """Render a Python annotation as a Ruby-style return type string."""
    if not type_str:
        return "void"
    type_name = type_str.split(".")[-1]

    optional = re.fullmatch(r"Optional(\w+)", type_name)
    if optional:
        inner = optional.group(1)
        return f"{inner}, nil" if inner in all_class_names else "Object, nil"

    vector = re.fullmatch(r"(\w+)Vector", type_name)
    if vector:
        inner = vector.group(1)
        return f"Array<{inner}>" if inner in all_class_names else "Array"

    if type_name in _PRIMITIVE_TYPES:
        return _PRIMITIVE_TYPES[type_name]

    return type_name if type_name in all_class_names else "Object"


UNKNOWN_TYPE = "?"
"""Reported when neither a wrapper annotation nor a C++ header declares the return type.

Deliberately not a guess. A name-based heuristic used to fill this gap and was wrong in
ways no reader could detect: ``ThermalZone#isConditioned`` matched an ``is[A-Z] ->
Boolean`` rule but actually returns ``boost::optional<std::string>``, so
``next unless zone.isConditioned`` silently skipped every zone. ``?`` tells the caller to
probe; ``Boolean`` told them to write a bug. ``operations._decorate`` already emits this
same sentinel when ``inspect.signature`` fails.
"""


def _wrapper_files(wrapper_dir: Path) -> list[Path]:
    return sorted(p for p in wrapper_dir.glob("openstudio*.py") if p.stem != "openstudio")


def _build(wrapper_dir: Path) -> dict[str, dict[str, dict]]:
    """Parse all wrapper files into ``{class: {method: {params, returns, static}}}``."""
    files = _wrapper_files(wrapper_dir)

    # Pass 1: cross-file module-level method assignments (carry return types).
    module_types: dict[str, dict[str, ParsedMethod]] = {}
    for path in files:
        for class_name, methods in _parse_module_level_types(path).items():
            module_types.setdefault(class_name, {}).update(methods)

    # Pass 2: class definitions. Keep the first occurrence of a class name.
    parsed: dict[str, ParsedClass] = {}
    for path in files:
        for cls in _parse_python_file(path):
            parsed.setdefault(cls.name, cls)

    all_class_names = set(parsed)

    # Apply cross-file methods: fill missing return types, add unseen methods.
    for class_name, methods in module_types.items():
        cls = parsed.get(class_name)
        if cls is None:
            continue
        for method_name, patched in methods.items():
            existing = cls.instance_methods.get(method_name)
            if existing is None:
                cls.instance_methods[method_name] = patched
            elif existing.return_type is None:
                existing.return_type = patched.return_type

    # C++ headers supply the return types the wrappers do not carry (i.e. nearly all of
    # them). Empty when no SDK headers are installed — then unannotated methods report
    # UNKNOWN_TYPE, which is honest.
    cpp = header_types()

    # Render to the public shape.
    result: dict[str, dict[str, dict]] = {}
    for class_name, cls in parsed.items():
        cpp_for_class = cpp.get(class_name, {})
        rendered: dict[str, dict] = {}
        for method in cls.static_methods.values():
            rendered[method.name] = _render(
                method, all_class_names, static=True, cpp_type=cpp_for_class.get(method.name),
            )
        for method in cls.instance_methods.values():
            rendered[method.name] = _render(
                method, all_class_names, static=False, cpp_type=cpp_for_class.get(method.name),
            )
        result[class_name] = rendered
    return result


def _render(
    method: ParsedMethod,
    all_class_names: set[str],
    *,
    static: bool,
    cpp_type: str | None = None,
) -> dict:
    """Resolve a return type from the best available source of truth.

    Precedence: wrapper annotation (the SWIG-synthesized Model/IdfObject families, which
    exist in no header) -> C++ header declaration (every hand-written domain class) ->
    ``UNKNOWN_TYPE``. The two sources overlap on 4 of 2,876 pairs, so the order is very
    nearly moot; it is stated explicitly rather than left to chance.
    """
    if method.return_type:
        returns = _resolve_return_type(method.return_type, all_class_names)
    elif cpp_type:
        returns = map_cpp_type(cpp_type, all_class_names)
    else:
        returns = UNKNOWN_TYPE
    return {"params": method.params, "returns": returns, "static": static}


def _locate_wrapper_dir() -> Path:
    import openstudio

    return Path(openstudio.__file__).parent


def signatures() -> dict[str, dict[str, dict]]:
    """Return ``{class_name: {method_name: {params, returns, static}}}``.

    Locates the wrapper files via the installed ``openstudio`` package
    (``openstudio.__file__`` — the SDK shipped inside the MCP image) and caches the
    parse for the process. Called by ``search_api`` to decorate methods with their
    parameter names and return types.
    """
    global _cache
    if _cache is None:
        _cache = _build(_locate_wrapper_dir())
    return _cache
