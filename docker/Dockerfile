# syntax=docker/dockerfile:1.4
FROM python:3.10-slim

WORKDIR /app
ENV PYTHONUNBUFFERED=1
ENV PIP_DEFAULT_TIMEOUT=180
ENV PIP_RETRIES=10
ENV PIP_DISABLE_PIP_VERSION_CHECK=1

COPY requirements.txt .
RUN --mount=type=cache,target=/root/.cache/pip \
    apt-get update && apt-get install -y --no-install-recommends curl \
    && rm -rf /var/lib/apt/lists/* \
    && pip install --retries 10 --timeout 180 -r requirements.txt

COPY . .
RUN mkdir -p /app/data /app/logs /app/config \
    && chmod +x docker/entrypoint.sh scripts/hummingbot_sidecar_runner.py

EXPOSE 5001

CMD ["./docker/entrypoint.sh"]
