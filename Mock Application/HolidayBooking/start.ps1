# Starts HolidayBooking, reusing a SQL Server that is already running and starting its own only if needed.
#   1. HolidayBooking's own SQL Server container already running -> leave it, use it.
#   2. Another SQL Server already listening on localhost:1433 (e.g. the main app's db) -> reuse it.
#   3. Otherwise -> start HolidayBooking's own SQL Server (data persisted in a Docker volume).
# The backend then waits for the server, creates the database if missing and runs the migrations.
$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot

$ownContainer = "holidaybooking-sqlserver-1"
$sqlPort = if ($env:HB_SHARED_SQL_PORT) { [int]$env:HB_SHARED_SQL_PORT } else { 1433 }

function Test-OwnRunning { [bool](docker ps -q --filter "name=^$ownContainer$" --filter status=running) }
function Test-PortOpen([int]$port) {
    $client = New-Object System.Net.Sockets.TcpClient
    try { $client.ConnectAsync("localhost", $port).Wait(1500) -and $client.Connected } catch { $false } finally { $client.Dispose() }
}

if (Test-OwnRunning) {
    Write-Host "HolidayBooking's SQL Server is already running: leaving it as is."
    $mode = "local"
} elseif (Test-PortOpen $sqlPort) {
    Write-Host "A SQL Server is already running on localhost:${sqlPort}: reusing it."
    $mode = "shared"
} else {
    Write-Host "No SQL Server found: starting HolidayBooking's own."
    $mode = "local"
}

if ($mode -eq "local") {
    $env:HB_DB_HOST = "sqlserver"; $env:HB_DB_PORT = "1433"
    docker compose --profile local-db up -d --build --wait
} else {
    $env:HB_DB_HOST = "host.docker.internal"; $env:HB_DB_PORT = "$sqlPort"
    docker compose up -d --build --wait
}
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

Write-Host ""
Write-Host "UI:        http://localhost:$(if ($env:HB_FRONTEND_PORT) { $env:HB_FRONTEND_PORT } else { 8180 })"
Write-Host "API docs:  http://localhost:$(if ($env:HB_BACKEND_PORT) { $env:HB_BACKEND_PORT } else { 8100 })/docs"
Write-Host "MCP:       http://localhost:$(if ($env:HB_MCP_PORT) { $env:HB_MCP_PORT } else { 8101 })/mcp"
