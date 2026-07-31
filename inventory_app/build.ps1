# Build exe (PyInstaller) for Windows.
# Run from inventory_app:
#   .\build.ps1

$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot

Write-Host "==> Installing PyInstaller..."
python -m pip install -q "pyinstaller>=6.0"

$DistName = "SkladUchet"

Write-Host "==> Cleaning old build..."
if (Test-Path "build") { Remove-Item -Recurse -Force "build" }
if (Test-Path "dist\$DistName") { Remove-Item -Recurse -Force "dist\$DistName" }
if (Test-Path "$DistName.spec") { Remove-Item -Force "$DistName.spec" }

Write-Host "==> PyInstaller (onedir)..."
python -m PyInstaller `
  --noconfirm `
  --clean `
  --windowed `
  --name $DistName `
  --onedir `
  --paths $PSScriptRoot `
  --hidden-import openpyxl `
  --hidden-import fpdf `
  --collect-all PyQt6 `
  main.py

$ExePath = "dist\$DistName\$DistName.exe"
if (-not (Test-Path $ExePath)) {
  throw "EXE not found: $ExePath"
}

Write-Host "==> Copying data files next to exe..."
Copy-Item -Force "config.json" "dist\$DistName\config.json"

# Deployed build: shablon folder next to exe
$CfgPath = "dist\$DistName\config.json"
$Cfg = Get-Content $CfgPath -Raw -Encoding UTF8
$Cfg = $Cfg -replace '"shablon":\s*"\.\./shablon"', '"shablon": "shablon"'
[System.IO.File]::WriteAllText((Resolve-Path $CfgPath), $Cfg, [System.Text.UTF8Encoding]::new($false))

$ShablonSrc = Join-Path (Split-Path $PSScriptRoot -Parent) "shablon"
$ShablonDst = "dist\$DistName\shablon"
New-Item -ItemType Directory -Force -Path $ShablonDst | Out-Null
if (Test-Path $ShablonSrc) {
  Copy-Item -Force (Join-Path $ShablonSrc "*.xlsx") $ShablonDst
}

New-Item -ItemType Directory -Force -Path @(
  "dist\$DistName\db",
  "dist\$DistName\backups",
  "dist\$DistName\reports"
) | Out-Null

$FullOut = (Resolve-Path "dist\$DistName").Path
Write-Host ""
Write-Host "Done: $FullOut"
Write-Host "Run: .\dist\$DistName\$DistName.exe"
Write-Host "Keep together: config.json, shablon, db, backups, reports, _internal"
