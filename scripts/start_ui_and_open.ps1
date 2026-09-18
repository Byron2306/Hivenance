# Start the Docker Compose stack and open the UI URL when ready
param(
    [int]$Port = 5000,
    [int]$TimeoutSeconds = 60
)

$settingsPath = Join-Path $PSScriptRoot "..\\config\\settings.yaml"
if (Test-Path $settingsPath) {
    try {
        $line = Get-Content $settingsPath | Where-Object { $_ -match '^walletconnect_project_id:' } | Select-Object -First 1
        if ($line) {
            $parts = $line -split ":", 2
            if ($parts.Count -ge 2) {
                $val = $parts[1].Trim().Trim("'`"")
                if ($val) { $env:WALLETCONNECT_PROJECT_ID = $val }
            }
        }
        $line2 = Get-Content $settingsPath | Where-Object { $_ -match '^oneinch_api_key:' } | Select-Object -First 1
        if ($line2) {
            $parts2 = $line2 -split ":", 2
            if ($parts2.Count -ge 2) {
                $val2 = $parts2[1].Trim().Trim("'`"")
                if ($val2) { $env:ONEINCH_API_KEY = $val2 }
            }
        }
    } catch {
    }
}

$composeFile = "docker/docker-compose.yml"
Write-Host "Starting Docker Compose (detached, build)..."
docker compose -f $composeFile up -d --build

$start = Get-Date
while ((New-TimeSpan -Start $start).TotalSeconds -lt $TimeoutSeconds) {
    try {
        $resp = Invoke-WebRequest -Uri ("http://127.0.0.1:{0}/" -f $Port) -UseBasicParsing -TimeoutSec 3
        if ($resp.StatusCode -ge 200 -and $resp.StatusCode -lt 400) {
            Write-Host ("UI is up - opening http://127.0.0.1:{0}" -f $Port)
            Start-Process ("http://127.0.0.1:{0}" -f $Port)
            exit 0
        }
    } catch {
        Start-Sleep -Seconds 1
    }
}

Write-Host ("Timed out waiting for UI on port {0} after {1} seconds. You can check containers with 'docker ps' and view logs with 'docker logs swarm-agent'." -f $Port, $TimeoutSeconds)
exit 1
