# Base image version tracked in versions.env (repo root). Update there when upgrading.
FROM python:3.13-slim
WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY server.py .

EXPOSE 8000

ENV MCP_TRANSPORT=streamable-http
ENV HOST=0.0.0.0
ENV PORT=8000

CMD ["python", "server.py"]
