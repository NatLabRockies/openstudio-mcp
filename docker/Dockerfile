ARG OPENSTUDIO_VERSION=3.11.0
FROM nrel/openstudio:${OPENSTUDIO_VERSION}
ARG OPENSTUDIO_VERSION

RUN apt-get update && apt-get install -y --no-install-recommends \
    python3 python3-venv python3-pip \
    ca-certificates curl \
    && rm -rf /var/lib/apt/lists/*

# Unprivileged account that confined measure/simulation subprocesses drop to
# (see mcp_server/_sandbox_exec.py). The server stays root; only the exec'd
# measure/EnergyPlus child runs as this uid when OSMCP_SANDBOX is enabled.
RUN useradd -r -u 1001 -s /usr/sbin/nologin sandbox

# ComStock measures (openstudio-standards-based templates for space types,
# constructions, HVAC, schedules). Only the measures/ directory is kept (~50 MB).
ARG COMSTOCK_TAG=2025-3
RUN curl -sL https://github.com/NatLabRockies/ComStock/archive/refs/tags/${COMSTOCK_TAG}.tar.gz | \
    tar xz -C /tmp && \
    mv /tmp/ComStock-*/resources/measures /opt/comstock-measures && \
    rm -rf /tmp/ComStock-*

ENV COMSTOCK_MEASURES_DIR=/opt/comstock-measures

# Common measures (openstudio-common-measures-gem — reporting, thermostats,
# envelope, PV, visualization, model cleanup, IDF injection, etc.)
ARG COMMON_MEASURES_TAG=v0.12.3
RUN curl -sL https://github.com/NatLabRockies/openstudio-common-measures-gem/archive/refs/tags/${COMMON_MEASURES_TAG}.tar.gz | \
    tar xz -C /tmp && \
    mv /tmp/openstudio-common-measures-gem-*/lib/measures /opt/common-measures && \
    rm -rf /tmp/openstudio-common-measures-gem-*

ENV COMMON_MEASURES_DIR=/opt/common-measures

# The nrel/openstudio base image already includes /var/oscli/ with bundled gems
# (openstudio-extension, openstudio-standards, etc.). No bundle install needed.
RUN apt-get purge -y curl && apt-get autoremove -y && rm -rf /var/lib/apt/lists/*

WORKDIR /repo

# venv
ENV VENV_PATH=/opt/venv
RUN python3 -m venv $VENV_PATH
ENV PATH="$VENV_PATH/bin:$PATH"

# Install third-party Python dependencies from package metadata before copying
# source. This keeps the expensive dependency layer cached when only package
# code, tests, scripts, or docs change.
COPY pyproject.toml /repo/pyproject.toml

RUN pip install --no-cache-dir -U pip "setuptools>=69" wheel \
    && python3 - <<'PY'
import subprocess
import sys
import tomllib

with open("pyproject.toml", "rb") as f:
    data = tomllib.load(f)

deps = data["project"].get("dependencies", []) + data["project"].get("optional-dependencies", {}).get("dev", [])
if deps:
    subprocess.check_call([sys.executable, "-m", "pip", "install", "--no-cache-dir", *deps])
PY

COPY mcp_server /repo/mcp_server

RUN pip install --no-cache-dir --no-deps -e .

# (Optional) If you want the container to include any other repo files too:
# COPY . /repo

COPY .claude/skills /skills
COPY docker /repo/docker
COPY scripts /repo/scripts
COPY tests /repo/tests
COPY README.md /repo/README.md
COPY LICENSE.md /repo/LICENSE.md
COPY .github /repo/.github

ENV OSMCP_RUN_ROOT=/runs
ENV OSMCP_MAX_CONCURRENCY=1
ENV OSMCP_CODE_MODE=0
ENV PYTHONUNBUFFERED=1
ENV OPENSTUDIO_MCP_MODE=dev

# Streamable-HTTP (remote multi-user) listens here; opt in with -e MCP_TRANSPORT=http
# (default transport is stdio). See docs/plans/multi-user-remote-mcp.md
EXPOSE 8000

CMD ["openstudio-mcp"]
