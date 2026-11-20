param([string]$PgBin = 'C:\Program Files\PostgreSQL\18\bin')
$ErrorActionPreference = 'Stop'
$root = Split-Path $PSScriptRoot -Parent
Set-Location $root
if (!(Test-Path .env)) { python scripts/configure.py }
if (!(Test-Path .venv/Scripts/python.exe)) { python -m venv .venv }
Write-Host 'Requires installed dependencies and PostgreSQL/Redis (see README).'
Push-Location backend
& ../.venv/Scripts/python.exe -m alembic upgrade head
if ($LASTEXITCODE -ne 0) { throw 'Migration failed' }
& ../.venv/Scripts/python.exe -m app.seed
if ($LASTEXITCODE -ne 0) { throw 'Seeding failed' }
Pop-Location
$logs = Join-Path $root '.local-logs'
New-Item -ItemType Directory -Force $logs | Out-Null
$api = Start-Process -FilePath "$root/.venv/Scripts/python.exe" -ArgumentList '-m','uvicorn','app.main:app','--host','127.0.0.1','--port','8000' -WorkingDirectory "$root/backend" -WindowStyle Hidden -PassThru -RedirectStandardOutput "$logs/backend.log" -RedirectStandardError "$logs/backend-error.log"
$node = (Get-Command node).Source
$web = Start-Process -FilePath $node -ArgumentList 'node_modules/vite/bin/vite.js','--host','127.0.0.1' -WorkingDirectory "$root/frontend" -WindowStyle Hidden -PassThru -RedirectStandardOutput "$logs/frontend.log" -RedirectStandardError "$logs/frontend-error.log"
@{backend=$api.Id;frontend=$web.Id} | ConvertTo-Json | Set-Content "$logs/pids.json"
Write-Host 'Frontend: http://localhost:5173  API: http://localhost:8000/docs'
Write-Host 'Logs in .local-logs. Use scripts/stop-local.ps1 to stop these processes.'
