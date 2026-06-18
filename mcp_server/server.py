from __future__ import annotations

import os

from fastmcp import FastMCP

from mcp_server.audit import AuditMiddleware
from mcp_server.config import ENABLE_CODE_MODE
from mcp_server.skills import register_all_skills
from mcp_server.stdout_suppression import (
    redirect_c_stdout_to_stderr,
    silence_openstudio_stdout_logger,
)


def _build_auth():
    """Auth verifier from MCP_AUTH env, or None (open server).

    Default: HTTP transport requires a token (secure-by-default); stdio stays open.
    MCP_AUTH=none   — no app auth; identity falls back to session id (use on a VPN).
    MCP_AUTH=token  — StaticTokenVerifier; MCP_TOKENS={"<token>":"<user>"}.
    MCP_AUTH=jwt    — JWTVerifier; MCP_JWT_PUBLIC_KEY or MCP_JWT_JWKS_URI
                      (+ optional MCP_JWT_ISSUER / MCP_JWT_AUDIENCE) for IdP/SSO.
    """
    http = os.environ.get("MCP_TRANSPORT", "stdio").lower() in ("http", "streamable-http")
    mode = os.environ.get("MCP_AUTH", "token" if http else "none").lower()
    if mode in ("", "none"):
        return None
    if mode == "token":
        import json

        from fastmcp.server.auth.providers.jwt import StaticTokenVerifier

        try:
            mapping = json.loads(os.environ.get("MCP_TOKENS", "") or "{}")
        except json.JSONDecodeError as e:
            raise ValueError(
                'MCP_TOKENS must be valid JSON mapping token -> username, '
                f'e.g. {{"s3cret":"alice"}} — got invalid JSON: {e}',
            ) from e
        if not isinstance(mapping, dict):
            raise ValueError("MCP_TOKENS must be a JSON object mapping token -> username")
        tokens = {t: {"client_id": u, "scopes": []} for t, u in mapping.items()}
        return StaticTokenVerifier(tokens=tokens)
    if mode == "jwt":
        from fastmcp.server.auth.providers.jwt import JWTVerifier

        return JWTVerifier(
            public_key=os.environ.get("MCP_JWT_PUBLIC_KEY") or None,
            jwks_uri=os.environ.get("MCP_JWT_JWKS_URI") or None,
            issuer=os.environ.get("MCP_JWT_ISSUER") or None,
            audience=os.environ.get("MCP_JWT_AUDIENCE") or None,
        )
    raise ValueError(f"Unknown MCP_AUTH mode: {mode!r}")


mcp = FastMCP(
    "openstudio-mcp",
    instructions=(
        "Building energy simulation server (OpenStudio SDK) with 150+ tools for "
        "creating, modifying, simulating, and analyzing building energy models. "
        "Use these tools for all building energy modeling tasks — if no tool "
        "exists for a task, ask the user before writing code. "
        "NEVER write scripts, code, or files to accomplish tasks that these "
        "tools already handle. Specifically: "
        "- Measures: ALWAYS use create_measure — never write measure.rb/.py/.xml "
        "directly. create_measure handles scaffolding, XML, checksums, and "
        "OS App compatibility. Workflow: create_measure → test_measure → apply_measure. "
        "- Results/data: use extract_summary_metrics, extract_end_use_breakdown, "
        "query_timeseries, extract_envelope_summary, extract_hvac_sizing — "
        "never write Python/SQL scripts to parse eplusout.sql. "
        "- Visualization: use view_model (3D geometry), view_simulation_data "
        "(charts/heatmaps), generate_results_report (HTML report) — never write "
        "matplotlib/plotly/HTML scripts. "
        "- Models: use create_new_building, create_bar_building, import_floorspacejs "
        "— never write raw IDF or OSM files. "
        "- Weather: use change_building_location (sets EPW+DDY+CZ in one call) "
        "or list_weather_files — never download or write weather files. "
        "- HVAC: use add_baseline_system, add_doas_system, add_vrf_system — "
        "never write OpenStudio SDK scripts to wire HVAC components. "
        "For custom HVAC measures, call search_wiring_patterns to get working "
        "Ruby wiring code, and search_api to verify methods exist. "
        "If a file path is given, use it directly. If a file operation fails, "
        "you may call list_files once to find the right path, then retry — "
        "do not call list_files more than once for the same file. "
        "Use list_weather_files for EPW discovery — do not use list_files for weather. "
        "To find objects by type, use list_model_objects(object_type). "
        "List tools default to 10 results — use filters to narrow, or "
        "max_results=0 for all. Prefer list tools before detail tools to "
        "find the right name. "
        "When polling get_run_status, wait at least 1-2 minutes between calls. "
        "For multi-step workflows, call list_skills() first."
    ),
    auth=_build_auth(),
)

register_all_skills(mcp)
mcp.add_middleware(AuditMiddleware())

if ENABLE_CODE_MODE:
    from fastmcp.experimental.transforms.code_mode import CodeMode
    mcp.add_transform(CodeMode())


def main():
    import sys

    silence_openstudio_stdout_logger()
    redirect_c_stdout_to_stderr()
    # Run-dir garbage collection is OFF by default. Enable explicitly with the
    # --gc / --gc-days CLI flag, or by setting OSMCP_RUN_RETENTION_DAYS>0.
    from mcp_server.config import RUN_RETENTION_DAYS
    from mcp_server.skills.simulation.retention import resolve_gc_days, start_retention_gc
    start_retention_gc(days=resolve_gc_days(sys.argv[1:], RUN_RETENTION_DAYS))
    transport = os.environ.get("MCP_TRANSPORT", "stdio").lower()
    if transport in ("http", "streamable-http"):
        mcp.run(
            transport="http",
            host=os.environ.get("MCP_HOST", "0.0.0.0"),  # noqa: S104 - container binds all interfaces; lock down via VPN/proxy
            port=int(os.environ.get("MCP_PORT", "8000")),
            path=os.environ.get("MCP_PATH", "/mcp"),
        )
    else:
        mcp.run()


if __name__ == "__main__":
    main()
