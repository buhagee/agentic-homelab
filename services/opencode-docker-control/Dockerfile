FROM docker:29-cli

RUN apk add --no-cache python3 py3-pip \
    && python3 -m venv /opt/venv

ENV PATH="/opt/venv/bin:${PATH}"
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1
WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY controller_logic.py server.py ./

USER 1000:1000

EXPOSE 8000

CMD ["python", "server.py"]
