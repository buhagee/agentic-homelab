# Base image version tracked in versions.env (repo root). Update there when upgrading.
FROM python:3.13-slim

RUN apt-get update && apt-get install -y --no-install-recommends \
    git \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Clone and install SkillClaw from source.
RUN git clone --depth=1 https://github.com/AMAP-ML/SkillClaw.git /opt/skillclaw

WORKDIR /opt/skillclaw

# Install BOTH the client proxy (evolve,sharing) and the evolve server (server).
# - skillclaw-evolve-server: background skill evolution (existing skillclaw service)
# - skillclaw (client proxy): records agent sessions for evolution (new skillclaw-proxy service)
RUN pip install --no-cache-dir -e ".[evolve,sharing,server]"

# Client-proxy entrypoint (writes config non-interactively, then starts proxy).
COPY proxy-entrypoint.sh /usr/local/bin/proxy-entrypoint.sh
RUN chmod +x /usr/local/bin/proxy-entrypoint.sh

# Hermes-session importer: converts both agents' native session logs into the
# SkillClaw session schema and writes them to the shared store for the evolve
# server to drain. Avoids routing live agent traffic through the proxy.
COPY import-hermes-sessions.py /opt/skillclaw/import-hermes-sessions.py

# No hardcoded ENTRYPOINT — each compose service sets its own command:
#   skillclaw service        -> skillclaw-evolve-server ...
#   skillclaw-proxy service  -> proxy-entrypoint.sh
