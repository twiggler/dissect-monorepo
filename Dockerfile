FROM ghcr.io/astral-sh/uv:python3.12-bookworm-slim

RUN apt-get update \
    && apt-get install -y --no-install-recommends git git-lfs rsync \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/*

# Activate git-lfs globally and install git-filter-repo via uv
ENV PATH="/root/.local/bin:$PATH"
RUN git lfs install \
    && uv tool install git-filter-repo

COPY . /monorepo-scripts
RUN chmod +x /monorepo-scripts/migrate/entrypoint.sh

# Configurable via -e on docker/podman run
ENV GIT_USER_EMAIL="migration@docker"
ENV GIT_USER_NAME="Docker Migration"

ENTRYPOINT ["/monorepo-scripts/migrate/entrypoint.sh"]
