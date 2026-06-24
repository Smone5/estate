#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
BACKEND_DIR="$ROOT_DIR/backend"
FRONTEND_DIR="$ROOT_DIR/frontend"
ENV_FILE="$ROOT_DIR/.env"
ENV_EXAMPLE="$ROOT_DIR/.env.example"

log() {
  printf '\n\033[1;34m%s\033[0m\n' "$1"
}

warn() {
  printf '\n\033[1;33m%s\033[0m\n' "$1"
}

die() {
  printf '\n\033[1;31m%s\033[0m\n' "$1" >&2
  exit 1
}

require_cmd() {
  command -v "$1" >/dev/null 2>&1 || die "Missing required command: $1"
}

compose() {
  docker compose "$@"
}

ensure_env_file() {
  if [[ ! -f "$ENV_FILE" ]]; then
    [[ -f "$ENV_EXAMPLE" ]] || die "Missing .env and .env.example."
    cp "$ENV_EXAMPLE" "$ENV_FILE"
    log "Created .env from .env.example"
  fi

  local current_key
  current_key="$(grep -E '^ENCRYPTION_KEY=' "$ENV_FILE" | head -n 1 | cut -d '=' -f 2- | tr -d '[:space:]' || true)"

  if [[ -z "$current_key" || "$current_key" == your-* ]]; then
    log "Generating ENCRYPTION_KEY for local UAT"
    local generated_key
    generated_key="$(
      cd "$BACKEND_DIR"
      uv run python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
    )"

    local tmp_file
    tmp_file="$(mktemp)"
    if grep -qE '^ENCRYPTION_KEY=' "$ENV_FILE"; then
      awk -v key="$generated_key" '
        BEGIN { done = 0 }
        /^ENCRYPTION_KEY=/ && done == 0 {
          print "ENCRYPTION_KEY=" key
          done = 1
          next
        }
        { print }
        END {
          if (done == 0) print "ENCRYPTION_KEY=" key
        }
      ' "$ENV_FILE" > "$tmp_file"
    else
      cp "$ENV_FILE" "$tmp_file"
      printf '\nENCRYPTION_KEY=%s\n' "$generated_key" >> "$tmp_file"
    fi
    mv "$tmp_file" "$ENV_FILE"
    log "Wrote ENCRYPTION_KEY to .env"
  else
    log "Using existing ENCRYPTION_KEY from .env"
  fi
}

env_value() {
  grep -E "^$1=" "$ENV_FILE" | head -n 1 | cut -d '=' -f 2- | sed 's/[[:space:]]*#.*$//' | tr -d '[:space:]' || true
}

set_env_value() {
  local key="$1"
  local value="$2"
  local tmp_file
  tmp_file="$(mktemp)"

  if grep -qE "^$key=" "$ENV_FILE"; then
    awk -v key="$key" -v value="$value" '
      BEGIN { done = 0 }
      $0 ~ "^" key "=" && done == 0 {
        print key "=" value
        done = 1
        next
      }
      { print }
    ' "$ENV_FILE" > "$tmp_file"
  else
    cp "$ENV_FILE" "$tmp_file"
    printf '\n%s=%s\n' "$key" "$value" >> "$tmp_file"
  fi

  mv "$tmp_file" "$ENV_FILE"
}

ensure_local_mailpit_smtp() {
  local smtp_host
  local smtp_password
  smtp_host="$(env_value SMTP_HOST)"
  smtp_password="$(env_value SMTP_PASSWORD)"

  if [[ -z "$smtp_host" || ( "$smtp_host" == "smtp.gmail.com" && -z "$smtp_password" ) ]]; then
    log "Configuring local Mailpit SMTP for UAT"
    set_env_value SMTP_HOST mailpit
    set_env_value SMTP_PORT 1025
    set_env_value SMTP_USERNAME ""
    set_env_value SMTP_PASSWORD ""
    set_env_value SMTP_USE_TLS false
    set_env_value SMTP_SENDER estate-steward@localhost
  else
    log "Using SMTP_HOST from .env: $smtp_host"
  fi
}

build_frontend() {
  log "Installing frontend dependencies if needed"
  if [[ ! -d "$FRONTEND_DIR/node_modules" ]]; then
    (cd "$FRONTEND_DIR" && npm install)
  fi

  log "Building production frontend"
  (cd "$FRONTEND_DIR" && npm run build)
}

wait_for_postgres() {
  log "Waiting for Postgres"
  local attempt
  for attempt in {1..30}; do
    if compose exec -T db pg_isready -U postgres -d estate >/dev/null 2>&1; then
      log "Postgres is ready"
      return 0
    fi
    sleep 2
  done
  die "Postgres did not become ready within 60 seconds. Run: docker compose logs db"
}

run_migrations() {
  log "Running Alembic migrations"
  compose run --rm app alembic upgrade head
}

start_services() {
  log "Starting Docker services: db"
  compose up -d db
  wait_for_postgres

  log "Building backend image"
  compose build app

  run_migrations

  log "Starting Docker services: app nginx langfuse"
  compose up -d app nginx langfuse
}

health_check() {
  log "Checking backend health"
  local attempt
  for attempt in {1..30}; do
    if curl -fsS http://localhost:8000/health >/dev/null 2>&1; then
      log "Backend health check passed"
      return 0
    fi
    sleep 2
  done
  warn "Backend health check did not pass within 60 seconds. Inspect with: docker compose logs app"
}

ollama_hint() {
  if curl -fsS http://localhost:11434/api/tags >/dev/null 2>&1; then
    log "Ollama is reachable at http://localhost:11434"
  else
    warn "Ollama is not reachable at http://localhost:11434. Core screens still start, but AI chat/OCR may degrade until Ollama is running with the configured models."
  fi
}

print_summary() {
  cat <<EOF

Local UAT is starting/running.

Open these URLs:
  Frontend / first admin setup:  http://localhost/admin
  Frontend app root:             http://localhost
  Backend health:                http://localhost:8000/health
  Backend API docs:              http://localhost:8000/docs
  Langfuse:                      http://localhost:3000
  Local email inbox (Mailpit):    http://localhost:8025

Useful commands:
  View logs:      docker compose logs -f app nginx db
  Stop services:  docker compose down
  Restart:        bash scripts/start_local.sh
  Reset all data: docker compose down -v   (destructive)

First run only:
  1. Open http://localhost/admin
  2. Create the executor/admin account
  3. Save the paper recovery key
  4. Sign in and begin session setup
  5. Register an heir and click "Send Invite"
  6. Open http://localhost:8025 to view the captured invite email

Returning UAT:
  1. Open http://localhost/admin
  2. Sign in with the existing executor/admin account
  3. Continue the existing estate session from the session list

EOF
}

main() {
  cd "$ROOT_DIR"
  require_cmd docker
  require_cmd npm
  require_cmd uv
  require_cmd curl

  ensure_env_file
  ensure_local_mailpit_smtp
  build_frontend
  start_services
  health_check
  ollama_hint
  print_summary
}

main "$@"
