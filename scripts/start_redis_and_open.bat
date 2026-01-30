@echo off
setlocal enabledelayedexpansion

set ROOT=%~dp0..
pushd "%ROOT%"

rem Ensure core settings for Docker run (network + redis host + ui port)
if exist "%ROOT%\\config\\settings.yaml" (
  powershell -NoProfile -Command ^
    "$p='%ROOT%\\config\\settings.yaml';" ^
    "$lines=Get-Content $p; " ^
    "function SetKV($key,$val){ " ^
    "  if($lines -match ('^'+[regex]::Escape($key)+':')){ " ^
    "    $lines = $lines | ForEach-Object { if($_ -match ('^'+[regex]::Escape($key)+':')) { $key+': '+$val } else { $_ } } " ^
    "  } else { $lines += ($key+': '+$val) } " ^
    "} " ^
    "SetKV 'network_enabled' 'true'; " ^
    "SetKV 'redis_host' 'redis'; " ^
    "SetKV 'redis_port' '6379'; " ^
    "SetKV 'ui_host' '0.0.0.0'; " ^
    "SetKV 'ui_port' '5000'; " ^
    "Set-Content -Path $p -Value $lines;"
)

rem Resolve UI port from settings.yaml (fallback to 5000)
set UIPORT=5000
for /f "tokens=1,2 delims=:" %%A in ('findstr /b /c:"ui_port:" "%ROOT%\\config\\settings.yaml"') do (
  set UIPORT=%%B
)
for /f "tokens=* delims= " %%A in ("%UIPORT%") do set UIPORT=%%A

rem Export WalletConnect Project ID if present in settings.yaml
for /f "tokens=1,2 delims=:" %%A in ('findstr /b /c:"walletconnect_project_id:" "%ROOT%\\config\\settings.yaml"') do (
  set WALLETCONNECT_PROJECT_ID=%%B
)
for /f "tokens=* delims= " %%A in ("%WALLETCONNECT_PROJECT_ID%") do set WALLETCONNECT_PROJECT_ID=%%A
set WALLETCONNECT_PROJECT_ID=%WALLETCONNECT_PROJECT_ID:"=%

rem Export 1inch API key if present in settings.yaml
for /f "tokens=1,2 delims=:" %%A in ('findstr /b /c:"oneinch_api_key:" "%ROOT%\\config\\settings.yaml"') do (
  set ONEINCH_API_KEY=%%B
)
for /f "tokens=* delims= " %%A in ("%ONEINCH_API_KEY%") do set ONEINCH_API_KEY=%%A
set ONEINCH_API_KEY=%ONEINCH_API_KEY:"=%

rem Ensure Docker is running
docker info >nul 2>&1
if errorlevel 1 (
  echo Starting Docker Desktop...
  start "" "C:\Program Files\Docker\Docker\Docker Desktop.exe"
  set /a tries=0
  :wait_docker
  timeout /t 2 /nobreak >nul
  docker info >nul 2>&1
  if errorlevel 1 (
    set /a tries+=1
    if !tries! lss 60 goto wait_docker
    echo Docker did not start in time. Continuing without redis.
    goto open_url
  )
)

echo Stopping any existing containers...
docker compose -f docker\docker-compose.yml down --remove-orphans

echo Clean rebuilding swarm-agent and pulling redis...
docker compose -f docker\docker-compose.yml build --no-cache swarm-agent
docker compose -f docker\docker-compose.yml pull redis
echo Starting swarm-agent + redis...
docker compose -f docker\docker-compose.yml up -d swarm-agent redis

:wait_ui
set /a tries=0
echo Waiting for UI to respond on http://127.0.0.1:%UIPORT%/ ...
:wait_ui_loop
powershell -NoProfile -Command ^
  "$u='http://127.0.0.1:%UIPORT%/';" ^
  "try { $r=Invoke-WebRequest -UseBasicParsing -TimeoutSec 2 $u; if($r.StatusCode -ge 200 -and $r.StatusCode -lt 500){ exit 0 } else { exit 1 } } catch { exit 1 }"
if errorlevel 1 (
  set /a tries+=1
  if !tries! lss 60 (
    timeout /t 2 /nobreak >nul
    goto wait_ui_loop
  )
  echo UI did not respond in time, opening anyway.
)

:open_url
set URL=http://127.0.0.1:%UIPORT%/
echo Opening %URL%
start "" "%URL%"

popd
endlocal
