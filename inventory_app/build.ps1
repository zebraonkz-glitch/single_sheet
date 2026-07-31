# Build exe (PyInstaller) for Windows — компактная сборка.
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

# Нужны только QtCore / QtGui / QtWidgets.
# --collect-all PyQt6 тянул QML/Multimedia/WebEngine (~200+ МБ) — не используем.
$Excludes = @(
  "PyQt6.QAxContainer",
  "PyQt6.QtBluetooth",
  "PyQt6.QtDBus",
  "PyQt6.QtDesigner",
  "PyQt6.QtHelp",
  "PyQt6.QtMultimedia",
  "PyQt6.QtMultimediaWidgets",
  "PyQt6.QtNfc",
  "PyQt6.QtOpenGL",
  "PyQt6.QtOpenGLWidgets",
  "PyQt6.QtPdf",
  "PyQt6.QtPdfWidgets",
  "PyQt6.QtPositioning",
  "PyQt6.QtPrintSupport",
  "PyQt6.QtQml",
  "PyQt6.QtQuick",
  "PyQt6.QtQuick3D",
  "PyQt6.QtQuickWidgets",
  "PyQt6.QtSensors",
  "PyQt6.QtSerialPort",
  "PyQt6.QtSpatialAudio",
  "PyQt6.QtSql",
  "PyQt6.QtSvg",
  "PyQt6.QtSvgWidgets",
  "PyQt6.QtTest",
  "PyQt6.QtTextToSpeech",
  "PyQt6.QtWebChannel",
  "PyQt6.QtWebEngineCore",
  "PyQt6.QtWebEngineWidgets",
  "PyQt6.QtWebSockets",
  "PyQt6.QtWebView",
  "PyQt6.QtXml",
  "PIL",
  "Pillow",
  "tkinter",
  "matplotlib",
  "numpy",
  "pandas"
)

# fpdf2 требует fontTools при импорте — не исключаем

$ExcludeArgs = @()
foreach ($mod in $Excludes) {
  $ExcludeArgs += "--exclude-module"
  $ExcludeArgs += $mod
}

Write-Host "==> PyInstaller (onedir, slim PyQt6)..."
python -m PyInstaller `
  --noconfirm `
  --clean `
  --windowed `
  --name $DistName `
  --onedir `
  --paths $PSScriptRoot `
  --hidden-import openpyxl `
  --hidden-import fpdf `
  @ExcludeArgs `
  main.py

$ExePath = "dist\$DistName\$DistName.exe"
if (-not (Test-Path $ExePath)) {
  throw "EXE not found: $ExePath"
}

# Доп. чистка: если хуки всё же подтянули тяжёлые Qt-пакеты
$Internal = "dist\$DistName\_internal"
$Qt6 = Join-Path $Internal "PyQt6\Qt6"
$DropDirs = @(
  (Join-Path $Qt6 "qml"),
  (Join-Path $Qt6 "qsci"),
  (Join-Path $Qt6 "translations")
)
foreach ($dir in $DropDirs) {
  if (Test-Path $dir) {
    Write-Host "==> Removing unused: $dir"
    Remove-Item -Recurse -Force $dir
  }
}

# Неиспользуемые плагины Qt (оставляем platforms / styles / imageformats)
$Plugins = Join-Path $Qt6 "plugins"
if (Test-Path $Plugins) {
  $KeepPlugins = @("platforms", "styles", "imageformats", "iconengines")
  Get-ChildItem $Plugins -Directory | Where-Object { $KeepPlugins -notcontains $_.Name } | ForEach-Object {
    Write-Host "==> Removing plugin: $($_.Name)"
    Remove-Item -Recurse -Force $_.FullName
  }
}

# Тяжёлые DLL, не нужные для QtWidgets-приложения
$BinDir = Join-Path $Qt6 "bin"
if (Test-Path $BinDir) {
  $DropDllPatterns = @(
    "opengl32sw.dll",
    "Qt6Quick*.dll",
    "Qt6Qml*.dll",
    "Qt6Designer*.dll",
    "Qt6Pdf*.dll",
    "Qt6Multimedia*.dll",
    "Qt6WebEngine*.dll",
    "Qt6WebView*.dll",
    "Qt6WebChannel*.dll",
    "Qt6WebSockets*.dll",
    "Qt6ShaderTools*.dll",
    "Qt6OpenGL*.dll",
    "Qt6Sensors*.dll",
    "Qt6Positioning*.dll",
    "Qt6Nfc*.dll",
    "Qt6Bluetooth*.dll",
    "Qt6Serial*.dll",
    "Qt6Sql*.dll",
    "Qt6Svg*.dll",
    "Qt6Test*.dll",
    "Qt6TextToSpeech*.dll",
    "Qt6Xml*.dll",
    "Qt63D*.dll",
    "Qt6SpatialAudio*.dll",
    "Qt6Charts*.dll",
    "Qt6DataVisualization*.dll",
    "Qt6RemoteObjects*.dll",
    "Qt6Scxml*.dll",
    "avcodec*.dll",
    "avformat*.dll",
    "avutil*.dll",
    "swresample*.dll",
    "swscale*.dll"
  )
  foreach ($pat in $DropDllPatterns) {
    Get-ChildItem $BinDir -Filter $pat -ErrorAction SilentlyContinue | ForEach-Object {
      Write-Host "==> Removing DLL: $($_.Name)"
      Remove-Item -Force $_.FullName
    }
  }
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

$SizeMb = [math]::Round(((Get-ChildItem "dist\$DistName" -Recurse -File | Measure-Object Length -Sum).Sum / 1MB), 1)
$FullOut = (Resolve-Path "dist\$DistName").Path
Write-Host ""
Write-Host "Done: $FullOut"
Write-Host "Size: $SizeMb MB"
Write-Host "Run: .\dist\$DistName\$DistName.exe"
Write-Host "Keep together: config.json, shablon, db, backups, reports, _internal"
