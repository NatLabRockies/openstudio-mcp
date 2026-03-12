"""Response-size guardrail tests — every paginated list tool stays under 10K chars.

Uses baseline model (System 07, 10 zones, ~60 surfaces, loads, loops).
Verifies per tool:
  - Default response <10K chars
  - Response shape: ok, count, correct items_key
  - Truncation metadata when total > max_results
  - max_results=0 returns all (no truncation)
  - Filters return correct subsets
  - Detail tools return ok
  - No redundant keys (list_files 'total')
"""
from __future__ import annotations

import asyncio
import json
import uuid

import pytest
from conftest import create_baseline_and_load, integration_enabled, server_params, unwrap
from mcp import ClientSession
from mcp.client.stdio import stdio_client

MAX_RESPONSE_CHARS = 10_000

# Paginated list tools: (tool_name, items_key, extra_args_for_default_call)
# Phase C: removed list_people_loads, list_lighting_loads, list_electric_equipment,
#   list_gas_equipment, list_infiltration, list_hvac_components
PAGINATED_TOOLS = [
    ("list_surfaces", "surfaces", {}),
    ("list_subsurfaces", "subsurfaces", {}),
    ("list_spaces", "spaces", {}),
    ("list_thermal_zones", "thermal_zones", {}),
    ("list_materials", "materials", {}),
    ("list_model_objects", "objects", {"object_type": "Space"}),
    ("list_zone_hvac_equipment", "zone_hvac_equipment", {}),
    ("list_files", "items", {}),
]


def _unique_name():
    return f"pytest_rsz_{uuid.uuid4().hex[:8]}"


def _unwrap_tool(tool_name, raw):
    """Unwrap MCP result."""
    return unwrap(raw)


@pytest.mark.integration
class TestResponseSizes:
    """Comprehensive response-size guardrail tests."""

    @pytest.fixture(scope="class")
    def session_data(self):
        """Create baseline model once, collect all responses for tests."""
        if not integration_enabled():
            pytest.skip("Set RUN_OPENSTUDIO_INTEGRATION=1")

        name = _unique_name()
        data = {}

        async def _setup():
            async with stdio_client(server_params()) as (read, write):
                async with ClientSession(read, write) as session:
                    await session.initialize()
                    zones = await create_baseline_and_load(session, name)
                    data["zones"] = zones

                    # -- Default responses (max_results=10) --
                    defaults = {}
                    for tool_name, _key, extra_args in PAGINATED_TOOLS:
                        raw = await session.call_tool(tool_name, extra_args)
                        defaults[tool_name] = _unwrap_tool(tool_name, raw)
                    data["defaults"] = defaults

                    # -- Unlimited responses (max_results=0) for tools with >10 items --
                    unlimited = {}
                    for tool_name, _key, extra_args in PAGINATED_TOOLS:
                        args = {**extra_args, "max_results": 0}
                        raw = await session.call_tool(tool_name, args)
                        unlimited[tool_name] = _unwrap_tool(tool_name, raw)
                    data["unlimited"] = unlimited

                    # -- Explicit max_results=5 for surfaces --
                    raw = await session.call_tool("list_surfaces", {"max_results": 5})
                    data["surfaces_max5"] = unwrap(raw)

                    # -- Explicit max_results=1 --
                    raw = await session.call_tool("list_surfaces", {"max_results": 1})
                    data["surfaces_max1"] = unwrap(raw)

                    # -- Filter: surfaces by type+boundary --
                    raw = await session.call_tool(
                        "list_surfaces",
                        {"surface_type": "Wall", "boundary": "Outdoors"},
                    )
                    data["surfaces_ext_walls"] = unwrap(raw)

                    raw = await session.call_tool(
                        "list_surfaces",
                        {"surface_type": "RoofCeiling", "max_results": 0},
                    )
                    data["surfaces_roofs"] = unwrap(raw)

                    # -- Filter: surfaces by space --
                    first_space = unwrap(
                        await session.call_tool("list_spaces", {"max_results": 1})
                    )
                    if first_space.get("ok") and first_space["spaces"]:
                        sp_name = first_space["spaces"][0]["name"]
                        data["first_space_name"] = sp_name
                        raw = await session.call_tool(
                            "list_surfaces", {"space_name": sp_name, "max_results": 0},
                        )
                        data["surfaces_by_space"] = unwrap(raw)

                    # -- Filter: subsurfaces by type --
                    raw = await session.call_tool(
                        "list_subsurfaces",
                        {"subsurface_type": "FixedWindow", "max_results": 0},
                    )
                    data["subsurfaces_windows"] = unwrap(raw)

                    # -- Filter: spaces by space_type --
                    raw = await session.call_tool(
                        "list_spaces",
                        {"space_type_name": "Baseline Model Space Type", "max_results": 0},
                    )
                    data["spaces_by_type"] = unwrap(raw)

                    # -- Filter: thermal zones by air loop --
                    air_loops = unwrap(await session.call_tool("list_air_loops", {}))
                    if air_loops.get("ok") and air_loops.get("air_loops"):
                        al_name = air_loops["air_loops"][0]["name"]
                        data["first_air_loop"] = al_name
                        raw = await session.call_tool(
                            "list_thermal_zones",
                            {"air_loop_name": al_name, "max_results": 0},
                        )
                        data["zones_by_air_loop"] = unwrap(raw)

                    # -- Filter: model objects by name_contains --
                    raw = await session.call_tool(
                        "list_model_objects",
                        {"object_type": "Space", "name_contains": "Core", "max_results": 0},
                    )
                    data["model_objs_filtered"] = _unwrap_tool("list_model_objects", raw)

                    # -- Filter: materials by type --
                    raw = await session.call_tool(
                        "list_materials",
                        {"material_type": "StandardOpaqueMaterial", "max_results": 0},
                    )
                    data["materials_opaque"] = unwrap(raw)

                    # -- Space type details (C3) --
                    st_list = unwrap(
                        await session.call_tool("list_model_objects",
                                                {"object_type": "SpaceType", "max_results": 1}),
                    )
                    if st_list.get("ok") and st_list.get("objects"):
                        st_name = st_list["objects"][0]["name"]
                        raw = await session.call_tool(
                            "get_space_type_details", {"space_type_name": st_name},
                        )
                        data["space_type_details"] = unwrap(raw)
                        data["space_type_name"] = st_name

                    # -- read_file default (C1) --
                    raw = await session.call_tool("list_files", {})
                    files_resp = unwrap(raw)
                    if files_resp.get("ok") and files_resp.get("items"):
                        # Find a file (not dir) to read
                        for item in files_resp["items"]:
                            if item.get("type") == "file":
                                raw = await session.call_tool(
                                    "read_file", {"file_path": item["path"]},
                                )
                                data["read_file_default"] = unwrap(raw)
                                break

                    # -- Detail tools --
                    # get_construction_details (via list_model_objects)
                    constr_objs = unwrap(
                        await session.call_tool("list_model_objects",
                                                {"object_type": "Construction", "max_results": 1}),
                    )
                    if constr_objs.get("ok") and constr_objs.get("objects"):
                        c_name = constr_objs["objects"][0]["name"]
                        raw = await session.call_tool(
                            "get_construction_details", {"construction_name": c_name},
                        )
                        data["construction_details"] = unwrap(raw)
                        data["construction_name"] = c_name

                    # get_load_details — try lights (use list_model_objects)
                    lights_objs = unwrap(
                        await session.call_tool("list_model_objects",
                                                {"object_type": "Lights", "max_results": 1}),
                    )
                    if lights_objs.get("ok") and lights_objs.get("objects"):
                        l_name = lights_objs["objects"][0]["name"]
                        raw = await session.call_tool(
                            "get_load_details", {"load_name": l_name},
                        )
                        data["load_details_lights"] = unwrap(raw)
                        data["load_name_lights"] = l_name

                    # get_load_details — infiltration
                    infil_objs = unwrap(
                        await session.call_tool("list_model_objects",
                                                {"object_type": "SpaceInfiltrationDesignFlowRate",
                                                 "max_results": 1}),
                    )
                    if infil_objs.get("ok") and infil_objs.get("objects"):
                        i_name = infil_objs["objects"][0]["name"]
                        raw = await session.call_tool(
                            "get_load_details", {"load_name": i_name},
                        )
                        data["load_details_infil"] = unwrap(raw)

                    # get_load_details — nonexistent name
                    raw = await session.call_tool(
                        "get_load_details", {"load_name": "DOES_NOT_EXIST_12345"},
                    )
                    data["load_details_missing"] = unwrap(raw)

            return data

        loop = asyncio.new_event_loop()
        try:
            return loop.run_until_complete(_setup())
        finally:
            loop.close()

    # -----------------------------------------------------------------------
    # Size budget: every default call < 10K chars
    # -----------------------------------------------------------------------

    def test_default_response_under_budget(self, session_data):
        """Every paginated list tool with defaults returns <10K chars."""
        failures = []
        for tool_name, _key, _args in PAGINATED_TOOLS:
            resp = session_data["defaults"][tool_name]
            size = len(json.dumps(resp))
            if size >= MAX_RESPONSE_CHARS:
                failures.append(f"{tool_name}: {size} chars")
        assert not failures, f"Over {MAX_RESPONSE_CHARS} chars: {failures}"

    def test_each_default_individually(self, session_data):
        """Per-tool size check — gives clear failure message per tool."""
        for tool_name, _key, _args in PAGINATED_TOOLS:
            resp = session_data["defaults"][tool_name]
            size = len(json.dumps(resp))
            assert size < MAX_RESPONSE_CHARS, (
                f"{tool_name} default response is {size} chars (limit {MAX_RESPONSE_CHARS})"
            )

    # -----------------------------------------------------------------------
    # Response shape: ok, count, items_key present
    # -----------------------------------------------------------------------

    def test_response_shape_ok_and_count(self, session_data):
        """Every list tool response has ok=True and count >= 0."""
        for tool_name, _key, _args in PAGINATED_TOOLS:
            resp = session_data["defaults"][tool_name]
            assert resp.get("ok") is True, f"{tool_name}: ok not True"
            assert isinstance(resp.get("count"), int), f"{tool_name}: count not int"
            assert resp["count"] >= 0, f"{tool_name}: count negative"

    def test_response_has_correct_items_key(self, session_data):
        """Every list tool response contains its items under the correct key."""
        for tool_name, items_key, _args in PAGINATED_TOOLS:
            resp = session_data["defaults"][tool_name]
            assert items_key in resp, (
                f"{tool_name}: expected key '{items_key}', got keys {list(resp.keys())}"
            )
            items = resp[items_key]
            assert isinstance(items, list), f"{tool_name}[{items_key}] is not a list"
            assert len(items) == resp["count"], (
                f"{tool_name}: count={resp['count']} but len({items_key})={len(items)}"
            )

    def test_no_unexpected_keys(self, session_data):
        """Default (non-truncated) responses don't have truncation keys."""
        for tool_name, items_key, _args in PAGINATED_TOOLS:
            resp = session_data["defaults"][tool_name]
            # If not truncated, should NOT have total_available
            if not resp.get("truncated"):
                assert "total_available" not in resp, (
                    f"{tool_name}: has total_available without truncated=True"
                )

    # -----------------------------------------------------------------------
    # Truncation metadata
    # -----------------------------------------------------------------------

    def test_truncation_surfaces(self, session_data):
        """list_surfaces truncates and reports total_available."""
        default = session_data["defaults"]["list_surfaces"]
        unlimited = session_data["unlimited"]["list_surfaces"]
        total = unlimited["count"]
        if total <= 10:
            pytest.skip("Baseline has <= 10 surfaces, no truncation expected")
        assert default["truncated"] is True
        assert default["total_available"] == total
        assert default["count"] == 10
        assert len(default["surfaces"]) == 10

    def test_truncation_materials(self, session_data):
        """list_materials truncates when >10 materials exist."""
        default = session_data["defaults"]["list_materials"]
        unlimited = session_data["unlimited"]["list_materials"]
        total = unlimited["count"]
        if total <= 10:
            pytest.skip("Baseline has <= 10 materials")
        assert default["truncated"] is True
        assert default["total_available"] == total
        assert default["count"] == 10

    def test_truncation_model_objects(self, session_data):
        """list_model_objects(Space) truncates when >10 spaces."""
        default = session_data["defaults"]["list_model_objects"]
        unlimited = session_data["unlimited"]["list_model_objects"]
        total = unlimited["count"]
        # Baseline has 10 spaces — exactly at limit, no truncation expected
        if total <= 10:
            assert default.get("truncated") is not True
        else:
            assert default["truncated"] is True
            assert default["total_available"] == total
            assert default["count"] == 10

    # -----------------------------------------------------------------------
    # max_results override
    # -----------------------------------------------------------------------

    def test_max_results_zero_returns_all(self, session_data):
        """max_results=0 returns all items with no truncation."""
        for tool_name, items_key, _args in PAGINATED_TOOLS:
            resp = session_data["unlimited"][tool_name]
            assert resp["ok"] is True, f"{tool_name}: not ok"
            assert resp.get("truncated") is not True, f"{tool_name}: still truncated"
            assert resp["count"] == len(resp[items_key]), (
                f"{tool_name}: count mismatch with items"
            )

    def test_max_results_5(self, session_data):
        """max_results=5 limits to 5 items."""
        resp = session_data["surfaces_max5"]
        total = session_data["unlimited"]["list_surfaces"]["count"]
        assert resp["ok"] is True
        if total > 5:
            assert resp["count"] == 5
            assert len(resp["surfaces"]) == 5
            assert resp["truncated"] is True
            assert resp["total_available"] == total

    def test_max_results_1(self, session_data):
        """max_results=1 limits to 1 item."""
        resp = session_data["surfaces_max1"]
        total = session_data["unlimited"]["list_surfaces"]["count"]
        assert resp["ok"] is True
        if total > 1:
            assert resp["count"] == 1
            assert len(resp["surfaces"]) == 1
            assert resp["truncated"] is True

    def test_unlimited_surfaces_more_than_10(self, session_data):
        """Baseline model has >10 surfaces (validates test premise)."""
        resp = session_data["unlimited"]["list_surfaces"]
        assert resp["count"] > 10, "Baseline should have >10 surfaces for truncation tests"

    # -----------------------------------------------------------------------
    # Filter: list_surfaces
    # -----------------------------------------------------------------------

    def test_filter_surfaces_type_and_boundary(self, session_data):
        """Filtered exterior walls returns only matching items."""
        resp = session_data["surfaces_ext_walls"]
        assert resp["ok"] is True
        assert resp["count"] > 0, "Baseline should have exterior walls"
        for s in resp["surfaces"]:
            assert s["surface_type"] == "Wall"
            assert s["outside_boundary_condition"] == "Outdoors"

    def test_filter_surfaces_roof_ceiling(self, session_data):
        """Filtering by RoofCeiling returns only roof/ceiling surfaces."""
        resp = session_data["surfaces_roofs"]
        assert resp["ok"] is True
        for s in resp["surfaces"]:
            assert s["surface_type"] == "RoofCeiling"

    def test_filter_surfaces_by_space(self, session_data):
        """Filtering by space_name returns surfaces belonging to that space."""
        resp = session_data.get("surfaces_by_space")
        if resp is None:
            pytest.skip("No spaces found")
        assert resp["ok"] is True
        assert resp["count"] > 0
        sp_name = session_data["first_space_name"]
        for s in resp["surfaces"]:
            assert s["space"] == sp_name, f"Surface {s['name']} not in space {sp_name}"

    def test_filter_reduces_count(self, session_data):
        """Filtered results have fewer items than unfiltered."""
        all_count = session_data["unlimited"]["list_surfaces"]["count"]
        filtered_count = session_data["surfaces_ext_walls"]["count"]
        assert filtered_count < all_count, "Exterior walls should be subset of all surfaces"

    # -----------------------------------------------------------------------
    # Filter: list_subsurfaces
    # -----------------------------------------------------------------------

    def test_filter_subsurfaces_by_type(self, session_data):
        """Filtering subsurfaces by type returns correct subset."""
        resp = session_data["subsurfaces_windows"]
        assert resp["ok"] is True
        # May be 0 if baseline has no windows (no wwr set)
        for s in resp["subsurfaces"]:
            assert s["subsurface_type"] == "FixedWindow"

    # -----------------------------------------------------------------------
    # Filter: list_spaces
    # -----------------------------------------------------------------------

    def test_filter_spaces_by_space_type(self, session_data):
        """Filtering spaces by space_type_name returns matching spaces."""
        resp = session_data["spaces_by_type"]
        assert resp["ok"] is True
        # All baseline spaces should have this space type
        assert resp["count"] == 10, "Baseline has 10 spaces with same space type"

    # -----------------------------------------------------------------------
    # Filter: list_thermal_zones by air loop
    # -----------------------------------------------------------------------

    def test_filter_zones_by_air_loop(self, session_data):
        """Filtering zones by air_loop_name returns zones on that loop."""
        resp = session_data.get("zones_by_air_loop")
        if resp is None:
            pytest.skip("No air loops in baseline model")
        assert resp["ok"] is True
        assert resp["count"] > 0

    # -----------------------------------------------------------------------
    # Filter: list_model_objects by name_contains
    # -----------------------------------------------------------------------

    def test_filter_model_objects_name_contains(self, session_data):
        """Filtering model objects by name_contains returns matching names."""
        resp = session_data["model_objs_filtered"]
        assert resp["ok"] is True
        assert resp["count"] > 0, "Baseline should have 'Core' spaces"
        for obj in resp["objects"]:
            assert "core" in obj["name"].lower(), (
                f"Object '{obj['name']}' doesn't contain 'core'"
            )
        # Should be subset of all spaces
        all_count = session_data["unlimited"]["list_model_objects"]["count"]
        assert resp["count"] < all_count

    def test_model_objects_has_type_field(self, session_data):
        """list_model_objects response includes the queried type."""
        resp = session_data["defaults"]["list_model_objects"]
        assert resp.get("type") == "Space"

    # -----------------------------------------------------------------------
    # Filter: list_materials by material_type
    # -----------------------------------------------------------------------

    def test_filter_materials_by_type(self, session_data):
        """Filtering materials by type returns correct subset."""
        resp = session_data["materials_opaque"]
        assert resp["ok"] is True
        all_count = session_data["unlimited"]["list_materials"]["count"]
        # Opaque materials should be a subset (there are also air gap, etc.)
        assert resp["count"] <= all_count

    # -----------------------------------------------------------------------
    # Detail tools
    # -----------------------------------------------------------------------

    def test_get_construction_details_ok(self, session_data):
        """get_construction_details returns ok with layer info."""
        resp = session_data.get("construction_details")
        if resp is None:
            pytest.skip("No constructions in baseline model")
        assert resp["ok"] is True
        assert resp.get("construction") or resp.get("name"), (
            f"Missing construction data in response: {list(resp.keys())}"
        )

    def test_get_construction_details_under_budget(self, session_data):
        """get_construction_details response < 10K chars."""
        resp = session_data.get("construction_details")
        if resp is None:
            pytest.skip("No constructions in baseline model")
        size = len(json.dumps(resp))
        assert size < MAX_RESPONSE_CHARS

    def test_get_load_details_lights(self, session_data):
        """get_load_details returns ok for a lighting load."""
        resp = session_data.get("load_details_lights")
        if resp is None:
            pytest.skip("No lighting loads in baseline model")
        assert resp["ok"] is True
        assert "load_type" in resp
        assert resp["load_type"] == "Lights"

    def test_get_load_details_infiltration(self, session_data):
        """get_load_details returns ok for infiltration."""
        resp = session_data.get("load_details_infil")
        if resp is None:
            pytest.skip("No infiltration in baseline model")
        assert resp["ok"] is True
        assert resp["load_type"] == "SpaceInfiltrationDesignFlowRate"

    def test_get_load_details_missing(self, session_data):
        """get_load_details returns ok=False for nonexistent load."""
        resp = session_data["load_details_missing"]
        assert resp["ok"] is False
        assert "not found" in resp.get("error", "").lower()

    def test_get_load_details_under_budget(self, session_data):
        """get_load_details response < 10K chars."""
        resp = session_data.get("load_details_lights")
        if resp is None:
            pytest.skip("No lighting loads")
        size = len(json.dumps(resp))
        assert size < MAX_RESPONSE_CHARS

    # -----------------------------------------------------------------------
    # list_files: no redundant 'total' key
    # -----------------------------------------------------------------------

    def test_list_files_no_redundant_total(self, session_data):
        """list_files response has 'count' but not 'total'."""
        resp = session_data["defaults"]["list_files"]
        assert "count" in resp
        assert "total" not in resp

    def test_list_files_items_have_name_and_type(self, session_data):
        """list_files items have name, path, type fields."""
        resp = session_data["defaults"]["list_files"]
        if resp["count"] == 0:
            pytest.skip("No files in run dir")
        item = resp["items"][0]
        assert "name" in item
        assert "path" in item
        assert "type" in item
        assert item["type"] in ("file", "dir")

    # -----------------------------------------------------------------------
    # Consistency: count matches len(items) for all unlimited calls
    # -----------------------------------------------------------------------

    def test_unlimited_count_matches_items_length(self, session_data):
        """For every tool, unlimited count == len(items)."""
        for tool_name, items_key, _args in PAGINATED_TOOLS:
            resp = session_data["unlimited"][tool_name]
            assert resp["count"] == len(resp[items_key]), (
                f"{tool_name}: count={resp['count']} != len({items_key})={len(resp[items_key])}"
            )

    # -----------------------------------------------------------------------
    # Brief mode: surfaces include boundary condition
    # -----------------------------------------------------------------------

    def test_surfaces_brief_has_boundary(self, session_data):
        """Default (brief) surface items include outside_boundary_condition."""
        resp = session_data["defaults"]["list_surfaces"]
        if resp["count"] == 0:
            pytest.skip("No surfaces")
        first = resp["surfaces"][0]
        assert "outside_boundary_condition" in first, (
            f"Brief surface missing outside_boundary_condition. Keys: {list(first.keys())}"
        )

    # -----------------------------------------------------------------------
    # C1: read_file default 50KB
    # -----------------------------------------------------------------------

    def test_read_file_default_under_budget(self, session_data):
        """read_file with defaults returns <50KB text."""
        resp = session_data.get("read_file_default")
        if resp is None:
            pytest.skip("No files to read")
        assert resp["ok"] is True
        # bytes_read should be <= 50000 (default max_bytes)
        assert resp.get("bytes_read", 0) <= 50_000

    # -----------------------------------------------------------------------
    # C3: get_space_type_details capped nested arrays
    # -----------------------------------------------------------------------

    def test_space_type_details_under_budget(self, session_data):
        """get_space_type_details response < 10K chars."""
        resp = session_data.get("space_type_details")
        if resp is None:
            pytest.skip("No space types")
        assert resp["ok"] is True
        size = len(json.dumps(resp))
        assert size < MAX_RESPONSE_CHARS

    def test_space_type_details_brief_loads(self, session_data):
        """get_space_type_details nested loads have brief format {name, schedule}."""
        resp = session_data.get("space_type_details")
        if resp is None:
            pytest.skip("No space types")
        st = resp["space_type"]
        # Check that load arrays exist and items have only name+schedule keys
        for key in ("people_loads", "lighting_loads", "electric_equipment_loads", "gas_equipment_loads"):
            assert key in st, f"Missing {key}"
            for item in st[key]:
                if isinstance(item, dict) and "_truncated" not in item:
                    assert "name" in item, f"{key} item missing 'name'"

