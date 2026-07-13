# syntax=docker/dockerfile:1

# ARM64/FEX SteamCMD base maintained in the same Docker Hub namespace.
ARG STEAMCMD_BASE_IMAGE=peozozo123/steamcmd:latest

# ============================================================
# Stage 1: Builder — compile/build dependencies only
# ============================================================
FROM ${STEAMCMD_BASE_IMAGE} AS builder

USER root
ENV DEBIAN_FRONTEND=noninteractive

RUN apt-get update && apt-get install -y --no-install-recommends \
    python3.12 \
    python3.12-venv \
    python3.12-dev \
    python-is-python3 \
    pip \
    build-essential \
    libyaml-dev \
    curl \
    ca-certificates \
    && rm -rf /var/lib/apt/lists/*

# Create virtual environment and install Python dependencies
WORKDIR /app
COPY requirements.txt ./
RUN python3 -m venv /opt/venv && \
    /opt/venv/bin/pip install --no-cache-dir -r requirements.txt && \
    /opt/venv/bin/python -c "import yaml, aiohttp, structlog"

# Download rcon-cli in builder stage (avoids curl/wget in runtime)
RUN DOWNLOAD_URL=$(curl -s https://api.github.com/repos/itzg/rcon-cli/releases/latest | \
                   jq -r '.assets[] | select(.name | contains("linux_arm64.tar.gz")) | .browser_download_url') && \
    if [ -z "$DOWNLOAD_URL" ]; then \
        exit 1; \
    fi && \
    curl -L "$DOWNLOAD_URL" -o /tmp/rcon-cli.tar.gz && \
    cd /tmp && \
    tar -xzf rcon-cli.tar.gz && \
    if [ -f rcon-cli ]; then \
        chmod +x rcon-cli && mv rcon-cli /usr/local/bin/rcon-cli; \
    else \
        find . -name "rcon-cli" -type f -exec chmod +x {} \; && \
        find . -name "rcon-cli" -type f -exec mv {} /usr/local/bin/rcon-cli \; ; \
    fi && \
    rm -rf /tmp/rcon-cli* /tmp/LICENSE /tmp/README.md

# ============================================================
# Stage 2: Runtime — minimal production image
# ============================================================
FROM ${STEAMCMD_BASE_IMAGE}

ARG STEAMCMD_BASE_IMAGE

LABEL maintainer="peozozo123" \
      version="1.1.3" \
      description="Palworld Dedicated Server with FEX emulation for ARM64" \
      architecture="arm64" \
      base-image="${STEAMCMD_BASE_IMAGE}"

USER root
ENV DEBIAN_FRONTEND=noninteractive

# Install runtime dependencies only (no build-essential, python3.12-dev, libyaml-dev)
RUN apt-get update && apt-get install -y --no-install-recommends \
    python3.12 \
    python3.12-venv \
    python-is-python3 \
    pip \
    procps \
    tar \
    gzip \
    cron \
    supervisor \
    jq \
    gosu \
    && apt-get purge -y --auto-remove curl wget \
    && rm -rf /var/lib/apt/lists/*

# Copy Python virtual environment from builder stage
COPY --from=builder /opt/venv /opt/venv
COPY --from=builder /usr/local/bin/rcon-cli /usr/local/bin/rcon-cli

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PATH="/opt/venv/bin:$PATH" \
    PYTHONPATH="/app/src" \
    PIP_NO_CACHE_DIR=1 \
    \
    SERVER_NAME="Palworld Server" \
    MAX_PLAYERS=32 \
    SERVER_PORT=8211 \
    REST_API_PORT=8212 \
    RCON_PORT=25575 \
    \
    BACKUP_ENABLED=true \
    AUTO_UPDATE=true \
    REST_API_ENABLED=true \
    MONITORING_MODE=both \
    IDLE_RESTART_ENABLED=true \
    IDLE_RESTART_MINUTES=30 \
    IDLE_RESTART_MODE=restart \
    PALWORLD_RUNTIME_DIR=/run/palworld \
    DISCORD_ENABLED=false \
    \
    LOG_LEVEL=INFO \
    BACKUP_INTERVAL=3600 \
    BACKUP_RETENTION_DAYS=7 \
    PUID=1002 \
    PGID=1002

RUN mkdir -p /app /run/palworld /home/steam/palworld_server/Pal/Saved/Config/LinuxServer /home/steam/backups /home/steam/logs/palworld /etc/supervisor/conf.d

WORKDIR /app
COPY --from=builder /app/requirements.txt ./
COPY src/ ./src/
COPY config/ ./config/
COPY scripts/ ./scripts/
COPY docker/supervisor/ /etc/supervisor/conf.d/
COPY docker/entrypoint.sh /entrypoint.sh
COPY --chmod=755 scripts/healthcheck.py /usr/local/bin/healthcheck
COPY --chmod=755 scripts/palworld_control.py /usr/local/bin/palworld-control

# Verify: config loading + Python package imports (ADMIN_PASSWORD needed for env var substitution)
RUN ADMIN_PASSWORD=verify_build python -c "from src.config_loader import get_config; get_config()" && \
    python -c "import yaml, aiohttp, structlog; yaml.safe_load(open('config/default.yaml'))"

RUN chown -R steam:steam \
    /app \
    /run/palworld \
    /home/steam && \
    chmod +x /entrypoint.sh /usr/local/bin/healthcheck && \
    chmod 755 /home/steam/palworld_server \
    /home/steam/backups \
    /home/steam/logs

EXPOSE ${SERVER_PORT}/udp \
       27015/udp \
       ${REST_API_PORT}/tcp \
       ${RCON_PORT}/tcp

HEALTHCHECK --interval=30s --timeout=10s --retries=3 --start-period=5m \
    CMD /usr/local/bin/healthcheck || exit 1

# Container will start as root to fix permissions and then drop to steam user via gosu
WORKDIR /home/steam

ENTRYPOINT ["/entrypoint.sh"]
CMD ["--start-server"]
