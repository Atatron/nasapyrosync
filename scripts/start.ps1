# PyroSync launcher for Windows (PowerShell). Double-click start.bat, or run:
#   powershell -ExecutionPolicy Bypass -File scripts\start.ps1
$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
Set-Location $Root

function Find-Python {
  foreach ($c in @(@("py", "-3.13"), @("py", "-3.12"), @("py", "-3.11"), @("python"), @("python3"))) {
    try {
      $exe = $c[0]; $args_ = @(); if ($c.Length -gt 1) { $args_ = $c[1..($c.Length - 1)] }
      & $exe @args_ -c "import sys; sys.exit(0 if sys.version_info >= (3, 11) else 1)" 2>$null
      if ($LASTEXITCODE -eq 0) { return ,$c }
    } catch { }
  }
  return $null
}

$VPy = Join-Path $Root ".venv\Scripts\python.exe"
if (-not (Test-Path $VPy)) {
  $py = Find-Python
  if ($null -eq $py) { Write-Host "PyroSync needs Python 3.11 or newer: https://www.python.org/downloads/ (tick 'Add python.exe to PATH')." -ForegroundColor Red; exit 1 }
  Write-Host "Creating virtual environment (.venv)..."
  $exe = $py[0]; $a = @(); if ($py.Length -gt 1) { $a = $py[1..($py.Length - 1)] }
  & $exe @a -m venv .venv
}

$Stamp = Join-Path $Root ".venv\.pyrosync-deps"
$Want = (Get-FileHash backend\requirements.lock.txt).Hash + (Get-FileHash backend\requirements.txt).Hash
if (-not (Test-Path $Stamp) -or ((Get-Content $Stamp -Raw).Trim() -ne $Want)) {
  Write-Host "Installing Python packages (first run can take a few minutes)..."
  & $VPy -m pip install --upgrade pip | Out-Null
  & $VPy -m pip install -r backend\requirements.lock.txt
  if ($LASTEXITCODE -ne 0) {
    Write-Host "Exact tested versions are not available for this Python; installing compatible versions instead..."
    & $VPy -m pip install -r backend\requirements.txt
    if ($LASTEXITCODE -ne 0) { exit 1 }
  }
  Set-Content -Path $Stamp -Value $Want
}

if (-not (Test-Path "frontend\dist\index.html")) {
  if (Get-Command npm -ErrorAction SilentlyContinue) {
    Write-Host "Building the web interface..."
    Push-Location frontend; npm ci; npm run build; Pop-Location
  } else {
    Write-Host "frontend\dist is missing and Node.js is not installed. Install Node.js 22 LTS from https://nodejs.org or use a package that includes frontend\dist." -ForegroundColor Red; exit 1
  }
}

if (-not (Test-Path ".env")) { Copy-Item ".env.example" ".env" }
Set-Location backend
$port = if ($env:PYROSYNC_PORT) { $env:PYROSYNC_PORT } else { "8000" }
Write-Host "Starting PyroSync on http://127.0.0.1:$port  (close this window or press Ctrl+C to stop)" -ForegroundColor Green
& $VPy -m pyrosync.cli serve @args
