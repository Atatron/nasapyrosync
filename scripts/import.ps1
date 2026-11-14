# Import FIRMS CSV/ZIP files or folders from PowerShell. Run scripts\start.bat once first (creates .venv).
#   powershell -ExecutionPolicy Bypass -File scripts\import.ps1 C:\Users\me\Downloads\indonesia.zip
#   powershell -ExecutionPolicy Bypass -File scripts\import.ps1 --dry-run D:\firms\new
# Stop the server first (the database allows one writer process), or import through the browser instead.
$Root = Split-Path -Parent $PSScriptRoot
$resolved = foreach ($a in $args) { if (Test-Path $a) { (Resolve-Path $a).Path } else { $a } }
Set-Location (Join-Path $Root "backend")
& (Join-Path $Root ".venv\Scripts\python.exe") -m pyrosync.cli import @resolved
