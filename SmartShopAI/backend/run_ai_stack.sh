#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$ROOT_DIR"

MILVUS_VERSION="${MILVUS_VERSION:-v2.5.27}"
MILVUS_COMPOSE="${MILVUS_COMPOSE:-docker-compose.milvus.yml}"
MILVUS_URL="https://github.com/milvus-io/milvus/releases/download/${MILVUS_VERSION}/milvus-standalone-docker-compose.yml"
EMBEDDING_COMPOSE="${EMBEDDING_COMPOSE:-docker-compose.embedding.yml}"
PYTHON_BIN="${PYTHON_BIN:-python}"
APP_HOST="${APP_HOST:-0.0.0.0}"
APP_PORT="${APP_PORT:-8000}"
EMBEDDING_WAIT_SECONDS="${EMBEDDING_WAIT_SECONDS:-600}"

require_command() {
  if ! command -v "$1" >/dev/null 2>&1; then
    echo "Missing required command: $1" >&2
    exit 1
  fi
}

ensure_env() {
  if [[ ! -f ".env" ]]; then
    cp ".env.example" ".env"
    echo "Created .env from .env.example. Edit .env if you need different ports, keys, or model endpoints."
  fi
}

ensure_docker() {
  require_command docker
  if ! docker ps >/dev/null 2>&1; then
    echo "Docker daemon is not running or not reachable. Start Docker Desktop first." >&2
    exit 1
  fi
}

download_milvus_compose() {
  if [[ -f "$MILVUS_COMPOSE" ]]; then
    return
  fi
  require_command curl
  echo "Downloading Milvus compose: $MILVUS_URL"
  curl -L "$MILVUS_URL" -o "$MILVUS_COMPOSE"
}

check_gpu() {
  echo "Checking NVIDIA GPU access from Docker..."
  if ! docker run --rm --gpus all nvidia/cuda:12.4.1-base-ubuntu22.04 nvidia-smi; then
    echo "Docker GPU check failed. Enable NVIDIA Container Toolkit / Docker Desktop WSL GPU support." >&2
    exit 1
  fi
}

start_milvus() {
  download_milvus_compose
  echo "Starting Milvus..."
  docker compose -f "$MILVUS_COMPOSE" up -d
}

start_embedding() {
  echo "Starting Qwen3-Embedding-4B GPU service..."
  docker compose -f "$EMBEDDING_COMPOSE" up -d
}

wait_embedding() {
  require_command curl
  local deadline=$((SECONDS + EMBEDDING_WAIT_SECONDS))
  local body='{"model":"Qwen/Qwen3-Embedding-4B","input":["health check"]}'
  echo "Waiting for embedding service at http://127.0.0.1:8080/v1/embeddings ..."
  until curl --noproxy "*" -s -f -X POST "http://127.0.0.1:8080/v1/embeddings" -H "Content-Type: application/json" -d "$body" >/dev/null; do
    if (( SECONDS >= deadline )); then
      echo "Embedding service did not become ready within ${EMBEDDING_WAIT_SECONDS} seconds." >&2
      exit 1
    fi
    echo "Embedding service is not ready yet."
    sleep 10
  done
  echo "Embedding service is ready."
}

build_index() {
  echo "Building Milvus product embedding index..."
  "$PYTHON_BIN" scripts/build_milvus_index.py --recreate
}

start_backend() {
  if command -v "$PYTHON_BIN" >/dev/null 2>&1; then
    "$PYTHON_BIN" -c "import socket, sys; s=socket.socket(); ok=s.connect_ex(('127.0.0.1', int(sys.argv[1]))) != 0; s.close(); sys.exit(0 if ok else 1)" "$APP_PORT" || {
      echo "Port ${APP_PORT} is already in use. Stop that process or run with APP_PORT=another_port." >&2
      exit 1
    }
  fi
  echo "Starting SmartShopAI backend on ${APP_HOST}:${APP_PORT}..."
  "$PYTHON_BIN" -m uvicorn app.main:app --host "$APP_HOST" --port "$APP_PORT"
}

stop_stack() {
  echo "Stopping embedding service..."
  docker compose -f "$EMBEDDING_COMPOSE" down || true
  if [[ -f "$MILVUS_COMPOSE" ]]; then
    echo "Stopping Milvus..."
    docker compose -f "$MILVUS_COMPOSE" down || true
  fi
}

status_stack() {
  docker ps --format "table {{.Names}}\t{{.Status}}\t{{.Ports}}"
}

case "${1:-start}" in
  start)
    ensure_env
    ensure_docker
    check_gpu
    start_milvus
    start_embedding
    wait_embedding
    build_index
    start_backend
    ;;
  infra)
    ensure_env
    ensure_docker
    check_gpu
    start_milvus
    start_embedding
    wait_embedding
    ;;
  index)
    ensure_env
    build_index
    ;;
  backend)
    ensure_env
    start_backend
    ;;
  stop)
    ensure_docker
    stop_stack
    ;;
  status)
    ensure_docker
    status_stack
    ;;
  *)
    echo "Usage: ./run_ai_stack.sh [start|infra|index|backend|stop|status]" >&2
    exit 1
    ;;
esac
