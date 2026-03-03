# mcp_server/version.py
from __future__ import annotations

from importlib.metadata import PackageNotFoundError
from importlib.metadata import version as _pkg_version

# Pin: this repo/container is expected to ship a fixed OpenStudio SDK version.
OPENSTUDIO_SDK_VERSION = "3.11.0"


def get_openstudio_mcp_version() -> str:
    """Return the installed package version for openstudio-mcp, if available."""
    try:
        return _pkg_version("openstudio-mcp")
    except PackageNotFoundError:
        # Fallback for editable/dev contexts where package metadata may not exist.
        return "0.0.0"


__version__ = get_openstudio_mcp_version()
