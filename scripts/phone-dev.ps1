<#
.SYNOPSIS
  Gets real phone calls reaching your local backend: opens an ngrok tunnel, records its URL as PUBLIC_BASE_URL in .env,
  restarts the backend and (with -Number) checks the Twilio side.

.EXAMPLE
  ./scripts/phone-dev.ps1 -Number +14155550100           # tunnel + checks, changes nothing on Twilio
  ./scripts/phone-dev.ps1 -Number +14155550100 -Apply    # also points the number's webhook at the tunnel

  The free ngrok URL changes every time ngrok restarts, so run this again after that (it is quick).
  Needs once: `ngrok config add-authtoken <token>`, and TWILIO_ACCOUNT_SID / TWILIO_AUTH_TOKEN / DEEPGRAM_API_KEY in .env.
#>
param(
  [string]$Number,
  [switch]$Apply,
  [int]$Port = 8000
)

$ErrorActionPreference = "Stop"
Set-Location (Split-Path $PSScriptRoot -Parent)
if (-not (Test-Path .env)) { throw ".env not found: copy .env.example to .env and fill it in first." }

function Get-Tunnel {
  try {
    (Invoke-RestMethod "http://127.0.0.1:4040/api/tunnels").tunnels |
      Where-Object { $_.public_url -like "https://*" -and $_.config.addr -match ":$Port$" } |
      Select-Object -First 1
  } catch { $null }
}

$tunnel = Get-Tunnel
if (-not $tunnel) {
  if (-not (Get-Command ngrok -ErrorAction SilentlyContinue)) { throw "ngrok is not installed (https://ngrok.com/download)." }
  Write-Host "Starting ngrok on port $Port..."
  Start-Process ngrok -ArgumentList "http", $Port -WindowStyle Minimized
  for ($i = 0; $i -lt 30 -and -not $tunnel; $i++) { Start-Sleep -Seconds 1; $tunnel = Get-Tunnel }
}
if (-not $tunnel) { throw "ngrok did not give a tunnel. Run 'ngrok config add-authtoken <token>' once, then try again." }
$url = $tunnel.public_url
Write-Host "Tunnel: $url"

# Rewrite .env without a BOM (docker compose would read a BOM as part of the first variable name).
$envPath = (Resolve-Path .env).Path
$lines = @(Get-Content $envPath)
if ($lines | Where-Object { $_ -match '^PUBLIC_BASE_URL=' }) {
  $lines = $lines | ForEach-Object { if ($_ -match '^PUBLIC_BASE_URL=') { "PUBLIC_BASE_URL=$url" } else { $_ } }
} else {
  $lines += "PUBLIC_BASE_URL=$url"
}
[System.IO.File]::WriteAllLines($envPath, [string[]]$lines, (New-Object System.Text.UTF8Encoding $false))

Write-Host "Restarting the backend so it reads the new URL..."
docker compose up -d --force-recreate --no-deps backend
if ($LASTEXITCODE -ne 0) { throw "docker compose failed." }
for ($i = 0; $i -lt 60; $i++) {
  try { if ((Invoke-RestMethod "http://localhost:$Port/health").status -eq "ok") { break } } catch { Start-Sleep -Seconds 2 }
}

if ($Number) {
  $check = @("--number", $Number)
  if ($Apply) { $check += "--apply" }
  docker compose exec -T backend python -m app.voice.phone_setup @check
  if ($LASTEXITCODE -ne 0) { Write-Host "Some checks failed: fix the [FAIL] lines above and run this again."; exit 1 }
  Write-Host "Ready: call $Number."
} else {
  Write-Host "Backend is up at $url. Re-run with -Number +<your twilio number> to check the Twilio side."
}
