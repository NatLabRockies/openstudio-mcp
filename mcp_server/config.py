from __future__ import annotations

import os
from pathlib import Path

RUN_ROOT = Path(os.environ.get("OPENSTUDIO_MCP_RUN_ROOT", os.environ.get("OSMCP_RUN_ROOT", "/runs"))).resolve()
RUN_ROOT.mkdir(parents=True, exist_ok=True)

def _safe_int(env_val: str, default: int) -> int:
    try:
        return int(env_val)
    except (ValueError, TypeError):
        return default

_raw_concurrency = os.environ.get("OPENSTUDIO_MCP_MAX_CONCURRENCY", os.environ.get("OSMCP_MAX_CONCURRENCY", "1"))
MAX_CONCURRENCY = _safe_int(_raw_concurrency, 1)

_raw_tail = os.environ.get("OPENSTUDIO_MCP_DEFAULT_LOG_TAIL", os.environ.get("OSMCP_LOG_TAIL_DEFAULT", "200"))
LOG_TAIL_DEFAULT = _safe_int(_raw_tail, 200)

OSCLI_GEMFILE = os.environ.get("OSCLI_GEMFILE", "/var/oscli/Gemfile")
OSCLI_GEM_PATH = os.environ.get("OSCLI_GEM_PATH", "/var/oscli/gems")

COMSTOCK_MEASURES_DIR = Path(os.environ.get("COMSTOCK_MEASURES_DIR", "/opt/comstock-measures"))
COMMON_MEASURES_DIR = Path(os.environ.get("COMMON_MEASURES_DIR", "/opt/common-measures"))
SKILLS_DIR = Path(os.environ.get("SKILLS_DIR", "/skills"))

INPUT_ROOT = Path(os.environ.get("OPENSTUDIO_MCP_INPUT_ROOT", "/inputs")).resolve()

ALLOWED_PATH_ROOTS = [
    Path("/repo").resolve(),
    RUN_ROOT,
    INPUT_ROOT,
    COMSTOCK_MEASURES_DIR,
    COMMON_MEASURES_DIR,
    SKILLS_DIR,
]

def is_path_allowed(p: Path) -> bool:
    rp = p.resolve()
    return any(str(rp).startswith(str(root) + os.sep) or rp == root for root in ALLOWED_PATH_ROOTS)
