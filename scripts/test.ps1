$ErrorActionPreference = 'Stop'
$root = Split-Path $PSScriptRoot -Parent
Set-Location "$root/backend"
& ../.venv/Scripts/python.exe -m ruff check .
if ($LASTEXITCODE -ne 0) { throw 'Backend lint failed' }
& ../.venv/Scripts/python.exe -m pytest --cov=app --cov-report=term-missing --cov-report=xml --cov-fail-under=80
if ($LASTEXITCODE -ne 0) { throw 'Backend tests failed' }
Set-Location "$root/frontend"
foreach ($task in @('lint','typecheck','test','build','e2e')) {
  npm run $task
  if ($LASTEXITCODE -ne 0) { throw "$task failed" }
}
