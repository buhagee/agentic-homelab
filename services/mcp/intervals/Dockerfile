# Base image version tracked in versions.env (repo root). Update there when upgrading.
FROM python:3.13-slim
WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends git && rm -rf /var/lib/apt/lists/*

# Clone intervals-mcp-server — supports MCP_TRANSPORT=streamable-http natively
RUN git clone --depth 1 \
    https://github.com/mvilanova/intervals-mcp-server.git \
    /app

RUN pip install --no-cache-dir -e . uvicorn

# Patch: set host to 0.0.0.0 (FastMCP defaults to 127.0.0.1, ignoring HOST env var)
RUN sed -i \
    's/FastMCP("intervals-icu", lifespan=setup_api_client)/FastMCP("intervals-icu", lifespan=setup_api_client, host="0.0.0.0")/' \
    src/intervals_mcp_server/mcp_instance.py

# Custom entry point: reads Authorization header → contextvar → get_config()
# so the shared container works for multiple users without API_KEY env var.
COPY run.py /app/run.py

ENV MCP_TRANSPORT=streamable-http
ENV HOST=0.0.0.0
ENV PORT=8000

CMD ["python", "run.py"]
