$root = Split-Path $PSScriptRoot -Parent
$file = Join-Path $root '.local-logs/pids.json'
if (Test-Path $file) {
  $pids = Get-Content $file | ConvertFrom-Json
  foreach ($id in @($pids.backend,$pids.frontend)) {
    $process = Get-Process -Id $id -ErrorAction SilentlyContinue
    if ($process -and $process.ProcessName -in @('python','node')) { Stop-Process -Id $id }
  }
  Remove-Item -LiteralPath $file
}
