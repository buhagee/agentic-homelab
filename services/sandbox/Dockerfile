FROM python:3.13-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    HOME=/tmp

WORKDIR /opt/sandbox

COPY base-requirements.txt .
RUN python -m pip install --no-cache-dir -r base-requirements.txt \
 && apt-get update -qq \
 && apt-get install -y --no-install-recommends curl \
 && rm -rf /var/lib/apt/lists/*

COPY runner.py /opt/sandbox/runner.py
COPY Home.py /opt/sandbox/Home.py

# Runtime uses the non-root UID configured for Hermes. Source workspace is
# mounted read-only; only /tmp is writable inside this image.
USER 1000:982
ENTRYPOINT ["python", "/opt/sandbox/runner.py"]
