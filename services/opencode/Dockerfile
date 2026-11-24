ARG OPENCODE_V2_NODE_VERSION=24.22.2
FROM node:${OPENCODE_V2_NODE_VERSION}-trixie-slim AS node

FROM debian:sid-slim@sha256:07a3205e8583fdff12d2b05bd030f50437e9fd340ee616df0c05dc77af75767b

USER root

COPY --from=node /usr/local/bin/node /usr/local/bin/node
COPY --from=node /usr/local/lib/node_modules/npm /usr/local/lib/node_modules/npm

ARG OPENCODE_V2_VERSION
ARG OPENCODE_V2_PNPM_VERSION

RUN apt-get update \
    && apt-get install -y --no-install-recommends ca-certificates curl git gh libstdc++6 passwd python3 procps \
    && rm -rf /var/lib/apt/lists/* \
    && groupadd --gid 1000 opencode \
    && useradd --uid 1000 --gid 1000 --home-dir /home/opencode --no-create-home --shell /usr/sbin/nologin opencode \
    && ln -sf /usr/local/lib/node_modules/npm/bin/npm-cli.js /usr/local/bin/npm \
    && ln -sf /usr/local/lib/node_modules/npm/bin/npx-cli.js /usr/local/bin/npx \
    && curl -fsSL "https://github.com/anomalyco/opencode/releases/download/v${OPENCODE_V2_VERSION}/opencode-linux-x64.tar.gz" -o /tmp/opencode-linux-x64.tar.gz \
    && curl -fsSL "https://github.com/anomalyco/opencode/releases/download/v${OPENCODE_V2_VERSION}/SHA256SUMS" -o /tmp/SHA256SUMS \
    && (cd /tmp && grep -F '  opencode-linux-x64.tar.gz' SHA256SUMS | sha256sum -c -) \
    && tar -xzf /tmp/opencode-linux-x64.tar.gz -C /usr/local/bin opencode \
    && chmod 0755 /usr/local/bin/opencode \
    && rm /tmp/opencode-linux-x64.tar.gz /tmp/SHA256SUMS \
    && npm install --global "pnpm@${OPENCODE_V2_PNPM_VERSION}" \
    && npm cache clean --force

USER 1000:1000
ENTRYPOINT ["opencode"]
