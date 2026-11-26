# Base image version tracked in versions.env (repo root). Update there when upgrading.
FROM python:3.13-slim
WORKDIR /app

RUN pip install --no-cache-dir paper-search-mcp

COPY run.py .

EXPOSE 8000

ENV FASTMCP_HOST=0.0.0.0
ENV FASTMCP_PORT=8000

CMD ["python", "run.py"]
