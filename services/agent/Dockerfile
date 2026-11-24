# Base image version tracked in versions.env (repo root). Update there when upgrading.
ARG HERMES_VERSION=latest
FROM nousresearch/hermes-agent:${HERMES_VERSION}

USER root

# Newer hermes-agent base images (>= v0.22) strip the standalone uv binary
# from the final layer; the venv's own pip (bootstrapped via ensurepip) can
# still install it, restoring /usr/local/bin/uv for the install steps below.
RUN /opt/hermes/.venv/bin/python -m ensurepip --upgrade 2>/dev/null || true \
 && /opt/hermes/.venv/bin/python -m pip install --no-cache-dir uv \
 && ln -sf /opt/hermes/.venv/bin/uv /usr/local/bin/uv

# Install messaging extras (python-telegram-bot[webhooks]) into the hermes venv
RUN /opt/hermes/.venv/bin/python -m ensurepip --upgrade 2>/dev/null || true \
 && /usr/local/bin/uv pip install "hermes-agent[messaging]" \
      --python /opt/hermes/.venv/bin/python \
 || /usr/local/bin/uv pip install "python-telegram-bot[webhooks]" \
      --python /opt/hermes/.venv/bin/python

# Hermes v0.22.7 needs the MCP v2 client; the bundled Google Workspace MCP
# still uses FastMCP v1, so keep its SDK and Google dependencies isolated.
RUN /usr/local/bin/uv pip install "mcp==2.3.0" \
      --python /opt/hermes/.venv/bin/python \
 && /usr/local/bin/uv venv --python /opt/hermes/.venv/bin/python /opt/google-workspace-venv \
 && /usr/local/bin/uv pip install \
      "google-api-python-client" \
      "google-auth-httplib2" \
      "google-auth-oauthlib" \
      "mcp==1.29.0" \
      --python /opt/google-workspace-venv/bin/python

RUN apt-get update -qq \
 && apt-get install -y --no-install-recommends curl ca-certificates chromium \
 && rm -rf /var/lib/apt/lists/*

# Ensure the runtime uid/gid can write HOME for Telegram locks and uv caches,
# and stdio MCP process state. The container runs with a configurable uid but a
# stable gid of 982 in this stack, so group-write on HOME is the critical bit.
RUN mkdir -p /opt/hermes/home \
 && chown -R 999:982 /opt/hermes/home \
 && chmod 2775 /opt/hermes/home

COPY google_workspace_mcp /opt/hermes/google_workspace_mcp
COPY sitecustomize.py /opt/hermes/sitecustomize.py

ENV HOME=/opt/hermes/home
ENV PYTHONPATH=/opt/hermes

# Entrypoint script
COPY start.sh /opt/hermes/start.sh
RUN chmod +x /opt/hermes/start.sh

USER 999
