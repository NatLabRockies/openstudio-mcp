"""Object management operations — delete, rename, list by type, generic access.

MANAGED_TYPES provides fast-path for common types. Unknown types fall back to
dynamic getter discovery via getattr(model, f"get{type_name}s").
"""
from __future__ import annotations

from typing import Any

from mcp_server.model_manager import get_model
from mcp_server.osm_helpers import fetch_object

# Each entry: OS type key -> model getter method (returns collection)
# The getter is model.get<Type>s() for most types.
MANAGED_TYPES: dict[str, str] = {
    # Spaces & zones
    "Space": "getSpaces",
    "ThermalZone": "getThermalZones",
    "BuildingStory": "getBuildingStorys",
    # HVAC loops
    "AirLoopHVAC": "getAirLoopHVACs",
    "PlantLoop": "getPlantLoops",
    # Coils (from component_properties registry)
    "CoilHeatingElectric": "getCoilHeatingElectrics",
    "CoilHeatingGas": "getCoilHeatingGass",  # OS pluralisation
    "CoilHeatingWater": "getCoilHeatingWaters",
    "CoilHeatingDXSingleSpeed": "getCoilHeatingDXSingleSpeeds",
    "CoilCoolingDXSingleSpeed": "getCoilCoolingDXSingleSpeeds",
    "CoilCoolingDXTwoSpeed": "getCoilCoolingDXTwoSpeeds",
    "CoilCoolingWater": "getCoilCoolingWaters",
    # Plant equipment
    "BoilerHotWater": "getBoilerHotWaters",
    "ChillerElectricEIR": "getChillerElectricEIRs",
    "CoolingTowerSingleSpeed": "getCoolingTowerSingleSpeeds",
    # Fans
    "FanConstantVolume": "getFanConstantVolumes",
    "FanVariableVolume": "getFanVariableVolumes",
    "FanOnOff": "getFanOnOffs",
    # Pumps
    "PumpVariableSpeed": "getPumpVariableSpeeds",
    "PumpConstantSpeed": "getPumpConstantSpeeds",
    # Loads
    "People": "getPeoples",
    "Lights": "getLightss",
    "ElectricEquipment": "getElectricEquipments",
    "GasEquipment": "getGasEquipments",
    "SpaceInfiltrationDesignFlowRate": "getSpaceInfiltrationDesignFlowRates",
    # Four-pipe beam / fan coil
    "AirTerminalSingleDuctConstantVolumeFourPipeBeam": "getAirTerminalSingleDuctConstantVolumeFourPipeBeams",
    "CoilCoolingFourPipeBeam": "getCoilCoolingFourPipeBeams",
    "CoilHeatingFourPipeBeam": "getCoilHeatingFourPipeBeams",
    "ZoneHVACFourPipeFanCoil": "getZoneHVACFourPipeFanCoils",
    # Constructions & materials
    "Construction": "getConstructions",
    "StandardOpaqueMaterial": "getStandardOpaqueMaterials",
    # Schedules
    "ScheduleRuleset": "getScheduleRulesets",
}


# ---------------------------------------------------------------------------
# Type name normalization — accept CamelCase, IDD colon, IDD underscore
# ---------------------------------------------------------------------------

def _normalize_type_name(raw: str) -> str:
    """Convert any format to CamelCase class name.

    Accepts:
      - CamelCase: CoilCoolingFourPipeBeam (returned as-is)
      - IDD colon: OS:Coil:Cooling:FourPipeBeam -> CoilCoolingFourPipeBeam
      - IDD underscore: OS_Coil_Cooling_FourPipeBeam -> CoilCoolingFourPipeBeam
    """
    if raw.startswith("OS:"):
        return raw[3:].replace(":", "")
    if raw.startswith("OS_"):
        return raw[3:].replace("_", "")
    return raw


def _resolve_getter(model, type_name: str):
    """Resolve a collection getter for the given type name.

    Fast-path: MANAGED_TYPES lookup.
    Fallback: try model.get{TypeName}s() dynamically.

    Returns (getter_callable, resolved_type_name) or (None, type_name).
    """
    norm = _normalize_type_name(type_name)

    # Fast-path
    if norm in MANAGED_TYPES:
        getter = getattr(model, MANAGED_TYPES[norm], None)
        if getter is not None:
            return getter, norm

    # Dynamic fallback: try get{Type}s()
    method_name = f"get{norm}s"
    getter = getattr(model, method_name, None)
    if getter is not None:
        return getter, norm

    return None, norm


# ---------------------------------------------------------------------------
# Base-class method blocklist for get_object_fields introspection
# ---------------------------------------------------------------------------

# Methods inherited from ModelObject / ParentObject / IdfObject / SWIG that
# return model objects, internal state, or are not useful property getters.
_BASE_BLOCKLIST = frozenset({
    # Identity / meta
    "handle", "iddObject", "iddObjectType", "name", "nameString",
    "comment", "fieldComment",
    # Relationships
    "parent", "children", "resources", "getRelationship",
    "model", "workspace",
    # Lifecycle
    "clone", "remove", "initialized",
    # Serialization
    "toIdfObject", "idfObject",
    # String representations
    "briefDescription",
    # SWIG internals
    "this", "thisown",
    # OpenStudio base queries
    "numFields", "numNonextensibleFields", "numExtensibleGroups",
    "extensibleGroups", "getExtensibleGroup",
    "outputVariableNames", "isSettableFromIdd",
    "sources", "targets",
    "getString", "getDouble", "getInt", "getUnsigned",
    "getQuantity", "getField",
    "isRemovable",
    "allowableChildTypes",
    "connectedObject", "connectedObjectPort",
    "getModelObjectSources", "getModelObjectTargets",
    "cast",
    # Loop/node navigation (return model objects)
    "loop", "airLoopHVAC", "plantLoop", "containingHVACComponent",
    "containingZoneHVACComponent", "containingStraightComponent",
    "inletModelObject", "outletModelObject",
    "inletPort", "outletPort",
    "getImpl",
    "createComponent",
    "disconnect",
    "addToNode",
    "removeFromLoop",
    "optionalCast",
})

# Prefixes to skip
_SKIP_PREFIXES = ("set", "Set", "_", "to_", "is", "are", "os", "autocalculate",
                  "autosize", "reset", "apply", "insert", "push", "pop",
                  "erase", "clear", "add", "remove", "replace", "create")


def _is_useful_getter(method_name: str) -> bool:
    """Return True if method_name looks like a property getter worth calling."""
    if method_name in _BASE_BLOCKLIST:
        return False
    for prefix in _SKIP_PREFIXES:
        if method_name.startswith(prefix):
            return False
    return not method_name.startswith("__")


def _extract_value(val, _depth: int = 0) -> tuple[Any, str]:
    """Extract a JSON-serializable value from a getter return.

    Returns (value, type_label) or raises TypeError if not serializable.
    When _depth < 1, follows definition links (PeopleDefinition, etc.)
    one level deep to expose their scalar fields inline.
    """
    # None / basic types
    if val is None:
        return None, "NoneType"
    if isinstance(val, (bool, int, float, str)):
        return val, type(val).__name__

    # OpenStudio Optional types (OptionalDouble, OptionalString, OptionalInt, etc.)
    if hasattr(val, "is_initialized"):
        if not val.is_initialized():
            return None, "Optional (empty)"
        inner = val.get()
        if isinstance(inner, (bool, int, float, str)):
            return inner, f"Optional{type(inner).__name__.capitalize()}"

        # Follow definition links 1 level deep (PeopleDefinition, LightsDefinition, etc.)
        if _depth < 1 and "Definition" in type(inner).__name__:
            fields = {}
            for m in dir(inner):
                if not _is_useful_getter(m):
                    continue
                attr = getattr(inner, m, None)
                if attr is None or not callable(attr):
                    continue
                try:
                    v, _t = _extract_value(attr(), _depth=1)
                    fields[m] = v
                except (TypeError, Exception):
                    continue
            if fields:
                return fields, f"definition({type(inner).__name__})"

        # Inner is a model object — skip
        raise TypeError("Optional contains model object")

    # OpenStudio enums — have valueName()
    if hasattr(val, "valueName"):
        return val.valueName(), "enum"

    # Vectors of strings
    if hasattr(val, "__iter__") and hasattr(val, "__len__"):
        try:
            items = list(val)
            if items and isinstance(items[0], str):
                return items, "list[str]"
        except Exception:
            pass

    # Follow definition links returned directly (not Optional-wrapped)
    if _depth < 1 and "Definition" in type(val).__name__:
        fields = {}
        for m in dir(val):
            if not _is_useful_getter(m):
                continue
            attr = getattr(val, m, None)
            if attr is None or not callable(attr):
                continue
            try:
                v, _t = _extract_value(attr(), _depth=1)
                fields[m] = v
            except (TypeError, Exception):
                continue
        if fields:
            return fields, f"definition({type(val).__name__})"

    raise TypeError(f"Non-serializable: {type(val).__name__}")


def _find_object_by_name(model, name: str, object_type: str | None = None):
    """Find a named object. If type given, search only that type.

    Returns (object, type_key) or (None, None).
    """
    if object_type:
        norm = _normalize_type_name(object_type)
        getter, _ = _resolve_getter(model, norm)
        if getter is not None:
            for obj in getter():
                if obj.nameString() == name:
                    return obj, norm
        return None, None

    # Search all MANAGED_TYPES
    for type_key, getter_name in MANAGED_TYPES.items():
        getter = getattr(model, getter_name, None)
        if getter is None:
            continue
        for obj in getter():
            if obj.nameString() == name:
                return obj, type_key
    return None, None


def _find_object(model, object_type: str, object_name: str | None = None,
                 object_handle: str | None = None):
    """Find an object by type + name or handle.

    Uses fetch_object (name/handle lookup) for normalized type.
    Falls back to collection scan for dynamic types.

    Returns (object, resolved_type) or (None, resolved_type).
    """
    norm = _normalize_type_name(object_type)

    # Try fetch_object first (uses getXByName / getX(uuid))
    obj = fetch_object(
        model, norm,
        name=object_name,
        handle=object_handle,
    )
    if obj is not None:
        return obj, norm

    # Fallback: scan collection (handles types where getByName doesn't exist)
    if object_name:
        getter, _ = _resolve_getter(model, norm)
        if getter is not None:
            for o in getter():
                try:
                    if o.nameString() == object_name:
                        return o, norm
                except Exception:
                    continue

    return None, norm


def delete_object(
    object_name: str,
    object_type: str | None = None,
) -> dict[str, Any]:
    """Delete a named object from the model."""
    try:
        model = get_model()

        obj, found_type = _find_object_by_name(model, object_name, object_type)
        if obj is None:
            return {"ok": False, "error": f"Object '{object_name}' not found"}

        # Warn about child objects for cascading types
        warnings = []
        if found_type == "Space":
            n_surfaces = len(obj.surfaces())
            n_loads = len(obj.people()) + len(obj.lights()) + len(obj.electricEquipment()) + len(obj.gasEquipment())
            if n_surfaces > 0:
                warnings.append(f"{n_surfaces} surfaces will also be removed")
            if n_loads > 0:
                warnings.append(f"{n_loads} load objects will also be removed")

        obj.remove()
        result: dict[str, Any] = {
            "ok": True,
            "deleted": object_name,
            "type": found_type,
        }
        if warnings:
            result["warnings"] = warnings
        return result

    except RuntimeError as e:
        return {"ok": False, "error": str(e)}
    except Exception as e:
        return {"ok": False, "error": f"Failed to delete object: {e}"}


def rename_object(
    object_name: str,
    new_name: str,
    object_type: str | None = None,
) -> dict[str, Any]:
    """Rename a named object in the model."""
    try:
        model = get_model()

        obj, found_type = _find_object_by_name(model, object_name, object_type)
        if obj is None:
            return {"ok": False, "error": f"Object '{object_name}' not found"}

        obj.setName(new_name)
        return {
            "ok": True,
            "old_name": object_name,
            "new_name": obj.nameString(),
            "type": found_type,
        }

    except RuntimeError as e:
        return {"ok": False, "error": str(e)}
    except Exception as e:
        return {"ok": False, "error": f"Failed to rename object: {e}"}


def list_model_objects(
    object_type: str,
    name_contains: str | None = None,
    max_results: int = 10,
) -> dict[str, Any]:
    """List objects of a given type with optional name filter and pagination.

    Accepts any OpenStudio type name in CamelCase, IDD colon (OS:Coil:Cooling:Water),
    or IDD underscore (OS_Coil_Cooling_Water) format. Common types use a fast-path;
    unknown types fall back to dynamic getter discovery.
    """
    try:
        model = get_model()

        getter, norm = _resolve_getter(model, object_type)
        if getter is None:
            return {
                "ok": False,
                "error": (
                    f"Unsupported type '{object_type}' (normalized: '{norm}'). "
                    f"No model.get{norm}s() method found. "
                    f"Common types: {', '.join(sorted(MANAGED_TYPES.keys())[:15])}..."
                ),
            }

        objects = getter()
        items = []
        for obj in objects:
            try:
                items.append({"handle": str(obj.handle()), "name": obj.nameString()})
            except Exception:
                items.append({"handle": str(obj.handle()), "name": "(unnamed)"})
        items.sort(key=lambda d: d["name"])

        if name_contains:
            nc = name_contains.lower()
            items = [i for i in items if nc in i["name"].lower()]

        total = len(items)
        truncated = max_results is not None and total > max_results
        if truncated:
            items = items[:max_results]

        resp: dict[str, Any] = {
            "ok": True, "type": norm, "count": len(items), "objects": items,
        }
        if truncated:
            resp["total_available"] = total
            resp["truncated"] = True
        return resp

    except RuntimeError as e:
        return {"ok": False, "error": str(e)}
    except Exception as e:
        return {"ok": False, "error": f"Failed to list objects: {e}"}


# ---------------------------------------------------------------------------
# W2: get_object_fields — generic property read via method introspection
# ---------------------------------------------------------------------------

def get_object_fields(
    object_type: str,
    object_name: str | None = None,
    object_handle: str | None = None,
) -> dict[str, Any]:
    """Read all properties of a model object via method introspection.

    Discovers getter methods on the object, calls each, returns typed values.
    Also lists available setter methods for use with set_object_property.

    Args:
        object_type: CamelCase, IDD colon, or IDD underscore format
        object_name: Object name (provide name or handle)
        object_handle: Object UUID handle
    """
    try:
        model = get_model()

        if not object_name and not object_handle:
            return {"ok": False, "error": "Provide object_name or object_handle"}

        obj, norm = _find_object(model, object_type, object_name, object_handle)
        if obj is None:
            identifier = object_name or object_handle
            return {"ok": False, "error": f"{norm} '{identifier}' not found"}

        properties: dict[str, dict] = {}
        setters: list[str] = []
        errors: list[str] = []

        all_methods = dir(obj)

        # Collect setter names for output
        for m in all_methods:
            if m.startswith("set") and m[3:4].isupper() and not m.startswith("setString"):
                setters.append(m)

        # Call useful getters
        for m in all_methods:
            if not _is_useful_getter(m):
                continue
            attr = getattr(obj, m, None)
            if attr is None or not callable(attr):
                continue
            try:
                val = attr()
                extracted, type_label = _extract_value(val)
                properties[m] = {"value": extracted, "type": type_label}
            except TypeError:
                # Method needs args or returns non-serializable
                continue
            except Exception as exc:
                errors.append(f"{m}: {exc}")
                continue

        setters.sort()
        result: dict[str, Any] = {
            "ok": True,
            "type": norm,
            "name": obj.nameString() if hasattr(obj, "nameString") else None,
            "handle": str(obj.handle()),
            "properties": properties,
            "setters": setters,
        }
        if errors:
            result["errors"] = errors[:5]
        return result

    except RuntimeError as e:
        return {"ok": False, "error": str(e)}
    except Exception as e:
        return {"ok": False, "error": f"Failed to get object fields: {e}"}


# ---------------------------------------------------------------------------
# W3: set_object_property — generic property write via official setters
# ---------------------------------------------------------------------------

def _derive_setter_name(property_name: str) -> str:
    """Derive setter method name from a getter/property name.

    If already starts with 'set' and next char is uppercase, use as-is.
    Otherwise prepend 'set' + capitalize first letter.
    """
    if property_name.startswith("set") and len(property_name) > 3 and property_name[3].isupper():
        return property_name
    return "set" + property_name[0].upper() + property_name[1:]


def _coerce_value(value: Any, current_val: Any = None) -> Any:
    """Coerce value to appropriate type for setter.

    Tries float first (most OS properties are double), then bool, then str.
    """
    if isinstance(value, (bool, int, float, str)):
        # If current value is float, coerce to float
        if isinstance(current_val, float) and not isinstance(value, float):
            try:
                return float(value)
            except (ValueError, TypeError):
                pass
        # If current value is int, coerce to int
        if isinstance(current_val, int) and not isinstance(value, int):
            try:
                return int(value)
            except (ValueError, TypeError):
                pass
        return value

    # String input — try numeric coercion
    if isinstance(value, str):
        try:
            return float(value)
        except ValueError:
            pass
        if value.lower() in ("true", "false"):
            return value.lower() == "true"
        return value

    return value


def set_object_property(
    object_type: str,
    property_name: str,
    value: Any,
    object_name: str | None = None,
    object_handle: str | None = None,
) -> dict[str, Any]:
    """Set a property on a model object using its official setter method.

    Args:
        object_type: CamelCase, IDD colon, or IDD underscore format
        property_name: Setter method name (e.g. "setEfficiency") or getter name
            (e.g. "efficiency" — will auto-derive "setEfficiency")
        value: New value (auto-coerced to match current type)
        object_name: Object name (provide name or handle)
        object_handle: Object UUID handle
    """
    try:
        model = get_model()

        if not object_name and not object_handle:
            return {"ok": False, "error": "Provide object_name or object_handle"}

        obj, norm = _find_object(model, object_type, object_name, object_handle)
        if obj is None:
            identifier = object_name or object_handle
            return {"ok": False, "error": f"{norm} '{identifier}' not found"}

        setter_name = _derive_setter_name(property_name)
        setter = getattr(obj, setter_name, None)
        if setter is None or not callable(setter):
            return {
                "ok": False,
                "error": f"No setter '{setter_name}' on {norm}. "
                         f"Use get_object_fields to see available setters.",
            }

        # Try to read old value via corresponding getter
        getter_name = setter_name[3].lower() + setter_name[4:]
        old_value = None
        getter = getattr(obj, getter_name, None)
        if getter and callable(getter):
            try:
                raw = getter()
                old_value, _ = _extract_value(raw)
            except Exception:
                pass

        # Coerce and set
        coerced = _coerce_value(value, old_value)
        try:
            result = setter(coerced)
        except TypeError:
            # Some setters return bool (success/fail)
            try:
                coerced = float(value) if isinstance(value, (int, str)) else value
                result = setter(coerced)
            except Exception as e2:
                return {"ok": False, "error": f"Setter {setter_name}({coerced!r}) failed: {e2}"}

        # Read new value
        new_value = None
        if getter and callable(getter):
            try:
                raw = getter()
                new_value, _ = _extract_value(raw)
            except Exception:
                pass

        resp: dict[str, Any] = {
            "ok": True,
            "type": norm,
            "name": obj.nameString() if hasattr(obj, "nameString") else None,
            "setter_method": setter_name,
            "old_value": old_value,
            "new_value": new_value,
        }
        # Some setters return False on failure
        if result is False:
            resp["ok"] = False
            resp["error"] = f"{setter_name} returned False — value may be out of range"
        return resp

    except RuntimeError as e:
        return {"ok": False, "error": str(e)}
    except Exception as e:
        return {"ok": False, "error": f"Failed to set property: {e}"}
