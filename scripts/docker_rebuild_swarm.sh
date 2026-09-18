#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

COMPOSE_FILE="${COMPOSE_FILE:-docker/docker-compose.yml}"
SERVICE="${SERVICE:-swarm-agent}"
UI_PORT="${HIVENANCE_UI_PORT:-5001}"

echo "Building ${SERVICE} with ${COMPOSE_FILE}..."
docker compose -f "$COMPOSE_FILE" build "$SERVICE"

echo "Recreating ${SERVICE}..."
docker compose -f "$COMPOSE_FILE" up -d --force-recreate "$SERVICE"

echo "Waiting for http://127.0.0.1:${UI_PORT}/api/status ..."
for _ in $(seq 1 30); do
  if curl -fsS "http://127.0.0.1:${UI_PORT}/api/status" >/dev/null; then
    echo "Swarm agent is healthy."
    echo "Dashboard:     http://127.0.0.1:${UI_PORT}/"
    echo "Integrations:  http://127.0.0.1:${UI_PORT}/integrations"
    exit 0
  fi
  sleep 2
done

echo "Swarm agent did not become healthy. Recent logs:"
docker logs --tail 120 "$SERVICE" || true
exit 1
