ARG OPENSTUDIO_VERSION=3.11.0
FROM nrel/openstudio:${OPENSTUDIO_VERSION}

RUN apt-get update && apt-get install -y --no-install-recommends \
    python3 python3-venv python3-pip \
    ca-certificates curl \
    && rm -rf /var/lib/apt/lists/*

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
ARG COMMON_MEASURES_TAG=v0.9.0
RUN curl -sL https://github.com/NatLabRockies/openstudio-common-measures-gem/archive/refs/tags/${COMMON_MEASURES_TAG}.tar.gz | \
    tar xz -C /tmp && \
    mv /tmp/openstudio-common-measures-gem-*/lib/measures /opt/common-measures && \
    rm -rf /tmp/openstudio-common-measures-gem-* && \
    apt-get purge -y curl && apt-get autoremove -y && rm -rf /var/lib/apt/lists/*

ENV COMMON_MEASURES_DIR=/opt/common-measures

WORKDIR /repo

# venv
ENV VENV_PATH=/opt/venv
RUN python3 -m venv $VENV_PATH
ENV PATH="$VENV_PATH/bin:$PATH"

# Copy everything needed to install the package
COPY pyproject.toml /repo/pyproject.toml
COPY mcp_server /repo/mcp_server
COPY docker /repo/docker

RUN pip install --no-cache-dir -U pip \
    && pip install --no-cache-dir -e ".[dev]"

# (Optional) If you want the container to include any other repo files too:
# COPY . /repo

COPY scripts /repo/scripts
COPY tests /repo/tests
COPY README.md /repo/README.md
COPY LICENSE.md /repo/LICENSE.md
COPY .github /repo/.github

ENV OSMCP_RUN_ROOT=/runs
ENV OSMCP_MAX_CONCURRENCY=1
ENV PYTHONUNBUFFERED=1
ENV OPENSTUDIO_MCP_MODE=dev

CMD ["openstudio-mcp"]