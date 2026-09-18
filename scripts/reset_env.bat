@echo off
REM Reset environment: stop docker, kill python/node, and clear logs

echo Stopping Docker compose (if present)...
docker compose down --volumes --remove-orphans 2>nul || docker-compose down --volumes --remove-orphans 2>nul

echo Stopping Python and Node processes (force)...
tasklist /FI "IMAGENAME eq python.exe" | find /I "python.exe" >nul && taskkill /F /IM python.exe /T || echo No python.exe processes found
tasklist /FI "IMAGENAME eq node.exe" | find /I "node.exe" >nul && taskkill /F /IM node.exe /T || echo No node.exe processes found

echo Cleaning logs, caches, and local DBs...
if exist logs (
    del /Q "logs\*" 2>nul
)
if exist logs\events rmdir /S /Q "logs\events" 2>nul
if exist logs\shared_cache.json del /Q "logs\shared_cache.json" 2>nul
if exist logs\analytics.db del /Q "logs\analytics.db" 2>nul
if exist logs\analytics.db-wal del /Q "logs\analytics.db-wal" 2>nul
if exist logs\analytics.db-shm del /Q "logs\analytics.db-shm" 2>nul
if exist logs\trades.csv del /Q "logs\trades.csv" 2>nul
if exist logs\activity.log del /Q "logs\activity.log" 2>nul

if exist data\swarm_data.db del /Q "data\swarm_data.db" 2>nul
if exist data\swarm_data.db-wal del /Q "data\swarm_data.db-wal" 2>nul
if exist data\swarm_data.db-shm del /Q "data\swarm_data.db-shm" 2>nul
if exist docker\data\swarm_data.db del /Q "docker\data\swarm_data.db" 2>nul
if exist docker\data\swarm_data.db-wal del /Q "docker\data\swarm_data.db-wal" 2>nul
if exist docker\data\swarm_data.db-shm del /Q "docker\data\swarm_data.db-shm" 2>nul

echo Reset complete.
echo Start services with: python main.py
pause
