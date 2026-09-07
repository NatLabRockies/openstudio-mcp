"""Parse the OpenStudio C++ headers into method return types.

Why headers and not the SWIG wrappers: the Python proxy files carry the class tree and
parameter names, but **no return-type annotations at all** — 0 of 57,516 class-body
methods in the 3.11.0 install declare one. Only ~2,876 methods (``Model``, ``IdfObject``,
``IdfExtensibleGroup``, ``GltfForwardTranslator``) get a type, and those come from
module-level ``Class.method = _fn`` assignments, not from the class bodies. Everything
else — every domain class an author actually touches — had no source of truth.

The SDK's own C++ headers ship inside the image and state it exactly:

    boost::optional<double> nominalCapacity() const;   ->  "Float, nil"
    double efficiency() const;                          ->  "Float"

Those two render identically under any name-based heuristic, yet ``.get`` is mandatory on
one and raises ``NoMethodError`` on the other. Only the declaration distinguishes them.

Headers and wrappers are complementary, not redundant: the ``Model#get*`` /
``IdfObject#to_*`` families are SWIG-synthesized and appear in no header, while domain
classes appear in headers but carry no annotation. ``_signatures`` consults both.

We read the headers as text (never compile them) and cache the parse per process.
"""
from __future__ import annotations

import os
import re
from collections.abc import Iterable
from pathlib import Path

# Default install location inside the MCP image. The Python wheel ships no headers, so
# this is deliberately independent of `openstudio.__file__` (which resolves to the wheel).
_INSTALL_GLOB = "/usr/local/openstudio-*/include/openstudio"
_ENV_VAR = "OSMCP_OPENSTUDIO_INCLUDE"

# `class MODEL_API ThermalZone : public HVACComponent {` — an export macro is the norm, but
# any number of macros may precede the name and they may take arguments:
#   class OS_DEPRECATED(3, 5, 0) MODEL_API TableMultiVariableLookup : public Curve
# Allowing only one *bare* macro silently dropped every method in such a file. The
# ALL-CAPS macro run is greedy, but backtracking still yields the right name for an
# all-caps class (`class MODEL_API AVM : public X`), since the trailing `(\w+)` must match.
# A trailing `;` (forward declaration, `class ThermalZone_Impl;`) matches none of `:{$`
# and is correctly ignored.
_CLASS_RE = re.compile(r"^\s*(?:class|struct)\s+(?:[A-Z][A-Z0-9_]*(?:\([^)]*\))?\s+)*(\w+)\s*(?::|\{|$)")
_ACCESS_RE = re.compile(r"^\s*(public|protected|private)\s*:")

# `%rename(ZUnit) openstudio::Unit;` / `%rename(toString) openstudio::measure::OSArgument::print;`
# — SWIG renames classes and methods, and the C++ headers declare only the pre-rename
# name. Without applying the directive, the exposed class never finds its declaration.
_RENAME_RE = re.compile(r"^\s*%rename\(\s*(\w+)\s*\)\s*([\w:]+)\s*;")

# `%extend openstudio::model::ModelObject{` — SWIG interface files declare the methods it
# synthesizes onto a class, which exist in no .hpp. ModelCore.i is where `toIdfObject`
# actually lives:  `IdfObject toIdfObject() const { return *self; }`. The bodies are plain
# C++, so the same declaration parser reads them. SWIG's own directives (`%template`,
# `%ignore`) sit at column 0 and cannot match _DECL_RE, which requires leading whitespace.
_EXTEND_RE = re.compile(r"^\s*%extend\s+(?:[\w:]+::)?(\w+)\s*\{")

# A member function declaration: <return type> <name>(<args>) [const] [override];
# The return type is captured loosely and refined by _split_return_type — C++ types are
# not a regular language, so we match broadly and validate after.
# The name may start uppercase (`boost::optional<double> CVRMSE() const;`). Constructors
# are still excluded: they have no return type, so the prefix group — which requires
# trailing whitespace — cannot match `ThermalZone(const Model&)`, and `explicit
# ThermalZone(...)` is caught by the name == class check.
_DECL_RE = re.compile(r"^\s+(.*?\s[\*&]?)\s*([A-Za-z]\w*)\s*\(")

# clang-format wraps a long declaration by putting the return type on its own line:
#     bool
#       setMinimumRegenerationInletAirRelativeHumidityforTemperatureEquation(double ...);
# Such a line is held and joined to the next rather than parsed and discarded.
_TYPE_ONLY_RE = re.compile(r"^\s*(?:(?:const|static|virtual|inline)\s+)*[\w:]+(?:<[^;{}]*>)?\s*[\*&]?\s*$")

# A line may *be* a macro call (REGISTER_LOGGER("..."); — 621x) or merely *start* with one
# (`OS_DEPRECATED(3, 7, 0) double maximumCyclingRate() const;` — 294x). Skipping both threw
# away real declarations, so the prefix is stripped and the remainder re-tested instead.
_MACRO_PREFIX_RE = re.compile(r"^\s*([A-Z][A-Z0-9_]{3,})\s*\(")

_QUALIFIERS = ("static", "virtual", "explicit", "inline", "constexpr", "friend", "typedef", "using")

# `OPENSTUDIO_ENUM(DefaultScheduleType, ((HoursofOperationSchedule)(...)(1)) ...)` declares
# a class via macro expansion — there is no `class` line and no member declarations to read,
# so the members below are the one thing here not parsed from a declaration. The macro emits
# the same set for every enum, and each row was confirmed against live Ruby rather than
# inferred. Note the macro may sit in a header named after a different class
# (DefaultScheduleType is declared inside DefaultScheduleSet.hpp).
_ENUM_MACRO_RE = re.compile(r"^\s*OPENSTUDIO_ENUM\s*\(\s*(\w+)")
_ENUM_MEMBERS = {
    "enumName": "std::string",  # class method
    "valueName": "std::string",
    "valueDescription": "std::string",
    "value": "int",
    "getValues": "std::vector<int>",  # class method
    # Ruby returns OpenStudio::StringIntMap — a SWIG container the bindings filter out of
    # the class list, so it renders Object like every other container wrapper.
    "getLookupMap": "std::map<std::string, int>",
}

_PRIMITIVES = {
    "void": "void",
    "bool": "Boolean",
    "double": "Float",
    "float": "Float",
    "int": "Integer",
    "unsigned": "Integer",
    "unsigned int": "Integer",
    "size_t": "Integer",
    "std::size_t": "Integer",
    "unsigned long": "Integer",
    "long": "Integer",
    "std::string": "String",
    "string": "String",
}

_cache: dict[str, dict[str, str]] | None = None
_cache_by_module: dict[str, dict[str, dict[str, str]]] | None = None
_cache_typedefs: dict[str, str] | None = None

# `using OptionalTime = boost::optional<Time>;` / `typedef std::vector<Point3d> Point3dVector;`
# Headers return these aliases directly (TimeSeries::intervalLength -> OptionalTime); without
# resolving them the type is a name the bindings lack and renders as an opaque Object.
_TYPEDEF_RE = re.compile(
    r"^\s*(?:typedef\s+(?P<t_target>.+?)\s+(?P<t_name>\w+)|using\s+(?P<u_name>\w+)\s*=\s*(?P<u_target>.+?))\s*;",
)

# Joins the return types of overloads that disagree (``std::vector<TimeSeries>`` vs
# ``boost::optional<TimeSeries>`` for SqlFile::timeSeries). SWIG collapses overloads to one
# ``(*args)`` entry, so the rendered signature must carry every possible return rather
# than silently pick the first declaration.
OVERLOAD_SEP = " | "


def _strip_comments(line: str, *, in_block: bool) -> tuple[str | None, bool]:
    """Remove comments. Returns (code or None, still-inside-a-block-comment).

    Block state must be tracked, not inferred per line. A doxygen continuation is not
    required to start with ``*``, and one that doesn't will otherwise read as code —
    ExteriorLoadInstance.hpp:51 is literally::

        /** Returns the number of instances this space load instance represents.
      This just forwards to multiplier() here but is included for consistency ...**/
        int quantity() const;

    The middle line carries a ``(``, so a line-at-a-time stripper feeds it into the
    continuation buffer and the real declaration behind it is lost. Line-prefix checks
    alone also miss CoilCoolingWater.hpp:29's ``*  <li> bool addToNode(Node & node);</li>``.
    """
    if in_block:
        if "*/" not in line:
            return None, True
        line = line.split("*/", 1)[1]

    # Consume any /* ... */ spans; an unterminated one opens a block.
    while "/*" in line:
        before, after = line.split("/*", 1)
        if "*/" in after:
            line = before + after.split("*/", 1)[1]
        else:
            return (before if before.strip() else None), True

    line = line.split("//", 1)[0] if "//" in line else line
    stripped = line.strip()
    if not stripped or stripped.startswith(("*", "#")):
        return None, False
    return line, False


def _strip_macro_prefix(line: str) -> str | None:
    """Strip leading macro invocations, returning the code behind them.

    Distinguishes a line that *is* a macro call from one that merely *starts* with one:

        REGISTER_LOGGER("openstudio.model.ThermalZone");        -> None   (skip)
        OS_DEPRECATED(3, 7, 0) double maximumCyclingRate() const;
                                    -> "double maximumCyclingRate() const;"

    Returns None when nothing but the macro call remains. Scans for the matching close
    paren rather than regexing, so nested parens in the arguments cannot truncate it.

    The OS_DEPRECATED version is deliberately dropped: these methods still exist in the
    bindings and need types like any other, and nothing renders the deprecation today.
    """
    remainder = line
    while True:
        match = _MACRO_PREFIX_RE.match(remainder)
        if not match:
            return remainder if remainder.strip() else None
        depth = 0
        for index in range(match.end() - 1, len(remainder)):
            if remainder[index] == "(":
                depth += 1
            elif remainder[index] == ")":
                depth -= 1
                if depth == 0:
                    break
        else:
            return None  # unterminated — a multi-line macro, not a declaration
        rest = remainder[index + 1 :]
        if not rest.strip() or rest.strip() == ";":
            return None  # the line was only a macro call
        remainder = rest


def _balanced(text: str) -> bool:
    """True when angle brackets balance — nested templates are real.

    e.g. ``boost::optional<std::pair<ConstructionBase, int>>``.
    """
    return text.count("<") == text.count(">")


def _split_return_type(prefix: str) -> str | None:
    """Reduce a declaration prefix to its return type, or None if it isn't one."""
    text = prefix.strip()
    for qualifier in _QUALIFIERS:
        # Repeatedly strip leading qualifiers: `static`, `virtual`, `static virtual`, ...
        while text.startswith(f"{qualifier} "):
            text = text[len(qualifier) + 1 :].strip()
    if not text or text in _QUALIFIERS:
        return None
    text = text.removeprefix("const ").strip().rstrip("*&").strip()
    if not text or not _balanced(text):
        return None
    # A bare identifier followed by nothing is a constructor-ish artifact, not a type.
    return text or None


def map_cpp_type(
    cpp: str,
    class_names: set[str] | None = None,
    typedefs: dict[str, str] | None = None,
    _depth: int = 0,
) -> str:
    """Render a C++ return type the way _signatures renders Python annotations.

    Conventions are deliberately identical to ``_signatures._resolve_return_type``:
    optionals as ``"X, nil"``, vectors as ``"Array<X>"``. Only the source of truth
    changes, never the output shape. ``typedefs`` (``header_typedefs``) expands
    ``OptionalTime`` / ``Point3dVector`` style aliases before rendering.
    """
    if OVERLOAD_SEP in cpp:
        rendered: list[str] = []
        for part in cpp.split(OVERLOAD_SEP):
            mapped = map_cpp_type(part, class_names, typedefs)
            if mapped not in rendered:
                rendered.append(mapped)
        return OVERLOAD_SEP.join(rendered)

    text = cpp.strip().removeprefix("const ").strip().rstrip("*&").strip()

    # Primitives before aliases: a header declares ``using string = std::wstring;`` which
    # would otherwise hijack every ``std::string`` return into Object.
    if text in _PRIMITIVES:
        return _PRIMITIVES[text]

    # Alias chains are short (Point3dVectorVector -> std::vector<Point3dVector> ->
    # std::vector<Point3d>); the depth cap only guards a pathological self-reference.
    if typedefs and text in typedefs and _depth < 8:
        return map_cpp_type(typedefs[text], class_names, typedefs, _depth + 1)

    # Namespace-qualified alias or class (``openstudio::OptionalTime``,
    # ``openstudio::model::Space``): resolve by the bare name. Templates keep their
    # ``::`` and fall through to the std::map/pair "Object" rule below.
    if "::" in text and "<" not in text:
        bare = text.rsplit("::", 1)[-1]
        if typedefs and bare in typedefs and _depth < 8:
            return map_cpp_type(typedefs[bare], class_names, typedefs, _depth + 1)
        if class_names is not None and bare in class_names:
            return bare

    optional = re.fullmatch(r"(?:boost|std)::optional\s*<\s*(.+?)\s*>", text)
    if optional:
        inner = map_cpp_type(optional.group(1), class_names, typedefs)
        # Optional<Optional<T>> is not a thing; a nested "X, nil" would render nonsense.
        inner = inner.split(",")[0].strip()
        return f"{inner}, nil"

    vector = re.fullmatch(r"std::vector\s*<\s*(.+?)\s*>", text)
    if vector:
        inner = map_cpp_type(vector.group(1), class_names, typedefs)
        return f"Array<{inner}>" if inner not in ("Object", "void") else "Array"

    if text in _PRIMITIVES:
        return _PRIMITIVES[text]

    # std::map/pair/tuple and friends: no useful Ruby rendering (7 occurrences repo-wide).
    if "<" in text or "::" in text:
        return "Object"

    if class_names is not None and text not in class_names:
        # Header-only classes absent from the bindings (Connection, ComponentWatcher,
        # DesignSpecificationZoneAirDistribution) must not render a name Ruby lacks.
        return "Object"
    return text or "Object"


def _parse_header(path: Path) -> dict[str, dict[str, str]]:
    """Parse one header into ``{class: {method: cpp_return_type}}`` (public members only)."""
    out: dict[str, dict[str, str]] = {}
    current: str | None = None
    # Nested classes/structs (``struct CalendarDay`` inside ``class Calendar``) and
    # inline method bodies must not hijack or prematurely close the enclosing class.
    # Brace depth is tracked per line: a class body closes when depth drops below the
    # level it had when the body's ``{`` opened — a method-body close keeps depth at
    # or above that level, the class's own ``};`` drops below it. stack entries are
    # (outer class, base depth) with base None until the body's ``{`` is seen (the
    # brace may sit on the following line).
    stack: list[tuple[str | None, int | None]] = []
    depth = 0
    pending = ""
    in_block = False

    for raw in path.read_text(encoding="utf-8", errors="replace").splitlines():
        line, in_block = _strip_comments(raw, in_block=in_block)
        if line is None:
            continue

        # A macro-declared enum class: register its generated members and move on. It does
        # not open a class body, so `current` is left alone.
        enum_match = _ENUM_MACRO_RE.match(line)
        if enum_match:
            out.setdefault(enum_match.group(1), {}).update(_ENUM_MEMBERS)
            continue

        class_match = _CLASS_RE.match(line) or _EXTEND_RE.match(line)
        if class_match:
            depth += line.count("{") - line.count("}")
            stack.append((current, depth if "{" in line else None))
            current = class_match.group(1)
            out.setdefault(current, {})
            pending = ""
            continue

        # Track brace depth and pop classes whose body has closed. A body opened on an
        # earlier line pins its base depth the first time a ``{`` line arrives.
        depth += line.count("{") - line.count("}")
        if stack and stack[-1][1] is None and "{" in line:
            stack[-1] = (stack[-1][0], depth)
        while stack and stack[-1][1] is not None and depth < stack[-1][1]:
            current, _ = stack.pop()

        if current is None:
            continue

        # A constructor's initializer list — the line after ``Ctor(...)``, which ends
        # with ``)`` so the multi-line continuation rule below already flushed — is a
        # continuation of the (skipped) constructor, not a declaration. Without the
        # skip, ``: m_member(...)...`` parses as a bogus method.
        if line.lstrip().startswith(":"):
            continue

        # REGISTER_LOGGER("openstudio.model.ThermalZone"); expands to
        # `static Logger logChannel();` — a real static accessor SWIG exposes, but the
        # macro line carries no declaration shape the parser can read, so the method
        # is registered literally. Logger is a bound class, so it renders as a name.
        if line.lstrip().startswith("REGISTER_LOGGER("):
            out[current].setdefault("logChannel", "Logger")
            continue

        # Access level is deliberately NOT filtered. This map only answers "what does X
        # return" for methods search_api already lists, and it lists them from `dir()` on
        # the live bindings — which expose some protected members (Model#addVersionObject).
        # Filtering to `public:` would drop their types without hiding the methods, so it
        # cost coverage and bought nothing. Data members can't be confused for methods:
        # they have no `(`, so _DECL_RE never matches them.
        if _ACCESS_RE.match(line):
            continue

        # A line that only invokes a macro is skipped; one that merely starts with a macro
        # keeps its declaration.
        line = _strip_macro_prefix(line)
        if line is None:
            continue

        # Join continuation lines. Two shapes, both real:
        #   `std::vector<Surface> findSurfaces(boost::optional<double> a,`  -> args wrap
        #   `bool` / `  setVeryLongName(double x);`                         -> type wraps
        pending = f"{pending} {line.strip()}" if pending else line
        if "(" in pending and ";" not in pending and not pending.rstrip().endswith(")"):
            continue
        if "(" not in pending and _TYPE_ONLY_RE.match(pending):
            continue
        candidate, pending = pending, ""

        decl = _DECL_RE.match(candidate)
        if not decl:
            continue

        prefix, name = decl.group(1), decl.group(2)
        if name == current or name.startswith("~"):  # ctor / dtor
            continue

        # NB: do NOT also reject cpp_type == current. A method may legitimately return its
        # own class — `Construction reverseConstruction() const;`,
        # `static GeneratorPhotovoltaic simple(const Model&);`, `ModelObject clone() const;`
        # — and the name == current check above already excludes constructors.
        cpp_type = _split_return_type(prefix)
        if cpp_type is None:
            continue

        _add_overload(out[current], name, cpp_type)

    return {cls: methods for cls, methods in out.items() if methods}


def _parse_typedefs(path: Path) -> dict[str, str]:
    """Collect ``typedef T Alias;`` / ``using Alias = T;`` from one header, comments stripped.

    Template aliases (``template <class T> using X = ...``) start with ``template`` and
    do not match; multi-line declarations are rare in the SDK and are skipped.
    """
    out: dict[str, str] = {}
    in_block = False
    for raw in path.read_text(encoding="utf-8", errors="replace").splitlines():
        line, in_block = _strip_comments(raw, in_block=in_block)
        if line is None:
            continue
        match = _TYPEDEF_RE.match(line)
        if not match:
            continue
        name = match.group("t_name") or match.group("u_name")
        target = match.group("t_target") or match.group("u_target")
        out.setdefault(name, target.strip())
    return out


def _add_overload(methods: dict[str, str], name: str, cpp_type: str) -> None:
    """Record one declaration's return type; overloads that disagree are joined.

    Same-type overloads (three ``bool setX(...)`` forms) stay a single entry. Different
    types join with ``OVERLOAD_SEP`` in declaration order; ``map_cpp_type`` renders each
    part and dedupes anything that maps to the same Ruby-style type.
    """
    existing = methods.get(name)
    if existing is None:
        methods[name] = cpp_type
    elif cpp_type not in existing.split(OVERLOAD_SEP):
        methods[name] = existing + OVERLOAD_SEP + cpp_type


def _locate_header_dir() -> Path | None:
    """Resolve the OpenStudio include dir, or None when unavailable.

    None is not an error: on a wheel-only box there are no headers, and callers simply
    fall back to whatever other source they have.
    """
    override = os.environ.get(_ENV_VAR)
    if override:
        path = Path(override)
        return path if path.is_dir() else None
    matches = sorted(Path(p) for p in __import__("glob").glob(_INSTALL_GLOB))
    return matches[-1] if matches else None


def _build(header_dir: Path) -> dict[str, dict[str, str]]:
    """Merge ``_build_by_module`` across modules: model/ first, then first-declaration-wins.

    The merged view is the fallback for classes whose bindings module has no header of
    its own (SWIG-synthesized classes, utilities bound from several wrapper files).
    Classes declared in more than one module (``ForwardTranslator`` in energyplus,
    gbxml, sdd, ...) must be resolved through ``header_types_by_module`` instead: the
    merge cannot know which module the bindings actually expose.
    """
    return _build_merged(_build_by_module(header_dir))


def header_module_for(wrapper_module: str, header_modules: Iterable[str]) -> str | None:
    """Map a SWIG wrapper file stem to the header subdir that declares its classes.

    Wrapper files are ``openstudio<module><part>.py`` (``openstudioenergyplus``,
    ``openstudiomodelcore``, ``openstudioutilitiessql``) while headers live under the
    bare module dir (``energyplus/``, ``model/``, ``utilities/``). Longest matching
    module prefix wins; None when nothing matches (an env-override include dir, a
    wrapper with no headers).
    """
    rest = wrapper_module.removeprefix("openstudio")
    candidates = [m for m in header_modules if m and rest.startswith(m)]
    return max(candidates, key=len) if candidates else None


def _build_typedefs(header_dir: Path) -> dict[str, str]:
    """``{alias: cpp_type}`` across every public header; model/ first, first declaration wins."""
    model_dir = header_dir / "model"
    headers = sorted(
        (p for ext in ("*.hpp", "*.hxx") for p in header_dir.rglob(ext) if "_Impl" not in p.name),
        key=lambda p: (not p.is_relative_to(model_dir), p),
    )
    out: dict[str, str] = {}
    for path in headers:
        for name, target in _parse_typedefs(path).items():
            out.setdefault(name, target)
    return out


def header_typedefs() -> dict[str, str]:
    """Return ``{alias: cpp_type}`` for the installed headers, cached; empty without headers."""
    global _cache_typedefs
    if _cache_typedefs is None:
        header_dir = _locate_header_dir()
        _cache_typedefs = _build_typedefs(header_dir) if header_dir else {}
    return _cache_typedefs


def _build_merged(by_module: dict[str, dict[str, dict[str, str]]]) -> dict[str, dict[str, str]]:
    result: dict[str, dict[str, str]] = {}
    for module in sorted(by_module, key=lambda m: (m != "model", m)):
        for cls, methods in by_module[module].items():
            target = result.setdefault(cls, {})
            for name, cpp_type in methods.items():
                target.setdefault(name, cpp_type)  # first declaration wins
    return result


def _build_by_module(header_dir: Path) -> dict[str, dict[str, dict[str, str]]]:
    """Parse every public header under ``header_dir``, recursing into submodules.

    Not limited to ``model/``: ``SqlFile`` (utilities/sql), ``RunControl`` and
    ``AirflowPath`` (both declared in airflow/contam/PrjObjects.hpp), ``UserModel``
    (isomodel) and friends live in nested subdirs under filenames that don't match
    the class, and their methods need the same sourced return types as the model
    classes. ``*_Impl.hpp`` are detail:: internals, not the public API — skipped
    everywhere.

    Ordering keeps two invariants. ``model/`` parses first, so first-declaration-wins
    preserves model precedence for classes declared in more than one module. ``.hpp``
    and ``.hxx`` files precede ``.i`` files, so a real declaration always wins over a
    SWIG ``%extend`` of the same name.

    Files are parsed module by module and each module's SWIG ``%rename`` directives
    applied before the global merge: the exposed class name (``ZUnit``, ``Any``,
    ``ContamForwardTranslator``, …) differs from the declared one (``Unit``,
    ``boost::any``, ``contam::ForwardTranslator``, …), and the pre-rename names are
    not unique across modules (six modules declare a ``ForwardTranslator``).
    """
    model_dir = header_dir / "model"

    def _ordered(paths: Iterable[Path]) -> list[Path]:
        # model/ first, each group alphabetical (first-declaration-wins below). When
        # the include root has no model/ subdir (e.g. an env override pointing at a
        # module dir directly), everything sorts alphabetically.
        return sorted(paths, key=lambda p: (not p.is_relative_to(model_dir), p))

    # .hpp/.hxx first so a real declaration always wins over a SWIG %extend of the
    # same name. .hxx carries real declarations too (IddFactory.hxx).
    headers = [
        p for p in _ordered(header_dir.rglob("*.hpp")) if not p.name.endswith("_Impl.hpp")
    ]
    headers += [
        p for p in _ordered(header_dir.rglob("*.hxx")) if not p.name.endswith("_Impl.hxx")
    ]
    i_files = _ordered(header_dir.rglob("*.i"))

    # Group by top-level module dir so each module's %rename directives can be
    # applied to that module's classes before the global merge.
    by_module: dict[str, list[Path]] = {}
    for path in headers + i_files:
        parts = path.relative_to(header_dir).parts
        by_module.setdefault(parts[0] if len(parts) > 1 else "", []).append(path)

    return {module: _parse_module(paths) for module, paths in by_module.items()}


def _parse_renames(path: Path) -> list[tuple[str, str]]:
    """Collect SWIG ``%rename(NewName) target;`` directives from an .i file."""
    renames = []
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        match = _RENAME_RE.match(line)
        if match:
            renames.append((match.group(1), match.group(2)))
    return renames


def _parse_module(paths: list[Path]) -> dict[str, dict[str, str]]:
    """Parse one module's headers + .i files, applying its SWIG %rename directives.

    Renames are applied in two passes — method renames first, so a class-rename
    alias created later copies the renamed methods too.
    """
    renames: list[tuple[str, str]] = []
    out: dict[str, dict[str, str]] = {}
    for path in paths:
        if path.suffix == ".i":
            renames.extend(_parse_renames(path))
        for cls, methods in _parse_header(path).items():
            target = out.setdefault(cls, {})
            for name, cpp_type in methods.items():
                target.setdefault(name, cpp_type)  # first declaration wins
    for new_name, target in renames:
        _apply_rename(out, new_name, target, method_only=True)
    for new_name, target in renames:
        _apply_rename(out, new_name, target, method_only=False)
    return out


def _apply_rename(
    out: dict[str, dict[str, str]],
    new_name: str,
    target: str,
    *,
    method_only: bool,
) -> None:
    """Apply one %rename to a module's parsed classes, in place.

    A target whose second-to-last segment is a parsed class carrying that method is a
    method rename (``openstudio::Unit::print`` -> ``toString``); otherwise the last
    segment is a class name (``openstudio::contam::ForwardTranslator`` ->
    ``ContamForwardTranslator``). Aliases are additive — the pre-rename name is kept.
    """
    segments = target.split("::")
    is_method = (
        len(segments) >= 2
        and segments[-2] in out
        and segments[-1] in out[segments[-2]]
    )
    if is_method != method_only:
        return
    if is_method:
        out[segments[-2]].setdefault(new_name, out[segments[-2]][segments[-1]])
        return
    old_name = segments[-1]
    if old_name in out and old_name != new_name:
        renamed = out.setdefault(new_name, {})
        for name, cpp_type in out[old_name].items():
            renamed.setdefault(name, cpp_type)


def header_types() -> dict[str, dict[str, str]]:
    """Return ``{class_name: {method_name: cpp_return_type}}``, cached per process.

    Empty dict when no headers are installed. Costs tens of ms for the ~880 public
    headers (``model/`` plus the nested ``utilities``, ``airflow``, ``isomodel``, …
    submodules), once.
    """
    global _cache
    if _cache is None:
        _cache = _build_merged(header_types_by_module())
    return _cache


def header_types_by_module() -> dict[str, dict[str, dict[str, str]]]:
    """Return ``{header_module: {class_name: {method_name: cpp_return_type}}}``, cached.

    Keyed by the top-level include subdir (``model``, ``utilities``, ``energyplus``, ...)
    so a class name declared in several modules resolves against the module the
    bindings expose (see ``header_module_for``). Empty when no headers are installed.
    """
    global _cache_by_module
    if _cache_by_module is None:
        header_dir = _locate_header_dir()
        _cache_by_module = _build_by_module(header_dir) if header_dir else {}
    return _cache_by_module
