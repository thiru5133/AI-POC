#!/usr/bin/env bash
# Starts GymBooking, reusing a SQL Server that is already running and starting its own only if needed.
#   1. GymBooking's own SQL Server container already running -> leave it, use it.
#   2. Another SQL Server already listening on localhost:1433 (e.g. the main app's db) -> reuse it.
#   3. Otherwise -> start GymBooking's own SQL Server (data persisted in a Docker volume).
# The backend then waits for the server, creates the database if missing and runs the migrations.
set -euo pipefail
cd "$(dirname "$0")"

OWN_CONTAINER="gymbooking-sqlserver-1"
SQL_PORT="${GB_SHARED_SQL_PORT:-1433}"

own_running() { [ -n "$(docker ps -q --filter "name=^${OWN_CONTAINER}$" --filter status=running)" ]; }
port_open() { (exec 3<>"/dev/tcp/localhost/$1") 2>/dev/null; }

if own_running; then
  echo "GymBooking's SQL Server is already running: leaving it as is."
  MODE=local
elif port_open "$SQL_PORT"; then
  echo "A SQL Server is already running on localhost:$SQL_PORT: reusing it."
  MODE=shared
else
  echo "No SQL Server found: starting GymBooking's own."
  MODE=local
fi

if [ "$MODE" = local ]; then
  export GB_DB_HOST=sqlserver GB_DB_PORT=1433
  docker compose --profile local-db up -d --build --wait
else
  export GB_DB_HOST=host.docker.internal GB_DB_PORT="$SQL_PORT"
  docker compose up -d --build --wait
fi

echo
echo "UI:        http://localhost:${GB_FRONTEND_PORT:-8280}"
echo "API docs:  http://localhost:${GB_BACKEND_PORT:-8200}/docs"
echo "MCP:       http://localhost:${GB_MCP_PORT:-8201}/mcp"
