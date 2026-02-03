param(
  [int]$Port = 49152,
  [string]$SharedSecret = ""
)
$repo = Resolve-Path (Join-Path $PSScriptRoot "..")
Set-Location $repo
# Load secret from settings.yaml if not provided
if (-not $SharedSecret) {
  $settingsPath = Join-Path $repo "config/settings.yaml"
  if (Test-Path $settingsPath) {
    try {
      $line = Get-Content $settingsPath | Where-Object { $_ -match '^buzz_shared_secret:' } | Select-Object -First 1
      if ($line) {
        $parts = $line -split ':', 2
        if ($parts.Count -ge 2) {
          $val = $parts[1].Trim().Trim("'\"")
          if ($val) { $SharedSecret = $val }
        }
      }
    } catch { }
  }
}
if ($SharedSecret) {
  $env:BUZZ_SHARED_SECRET = $SharedSecret
}
Write-Host "Starting BuzzService on http://127.0.0.1:$Port"
python -m uvicorn buzzservice.service:app --reload --port $Port
