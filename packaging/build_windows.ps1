# Fase 9B - build riproducibile di Nasdaq-100-Monitor-Windows.zip, SOLO su Windows 10/11 a 64 bit.
# (File solo ASCII: PowerShell 5 legge male gli accenti in un file senza BOM.)
#
# Serve: Python 3.12 a 64 bit installato da python.org (solo sul PC che fa la build, NON su quello di chi usa l'app)
# e Internet (librerie da PyPI; con -ConInternet anche i dati pubblici di mercato per la prova completa).
#
#   powershell -ExecutionPolicy Bypass -File packaging\build_windows.ps1 [-ConInternet] [-SenzaTest]
#
# Passi: 1 controlli  2 ambiente Python separato (.venv-win)  3 test automatici  4 file pubblici e icona
#        5 PyInstaller  6 controllo del pacchetto (nessun dato personale)  7 prova dell'eseguibile vero  8 ZIP + SHA-256
param([switch]$ConInternet, [switch]$SenzaTest)
$ErrorActionPreference = "Stop"
$Root = Split-Path $PSScriptRoot -Parent
Set-Location $Root

function Step($t) { Write-Host ""; Write-Host "== $t" -ForegroundColor Cyan }
function Run($exe, [string[]]$a) {
    & $exe @a
    if ($LASTEXITCODE -ne 0) { throw "comando non riuscito ($LASTEXITCODE): $exe $($a -join ' ')" }
}

Step "1. controlli"
if ($env:OS -ne "Windows_NT") { throw "questa build si fa solo su Windows" }
if (Test-Path "portafoglio") { Write-Host "nota: la cartella portafoglio/ esiste qui, ma non entra mai nel pacchetto (elenco chiuso dei file pubblici)" }
$py = $null
foreach ($c in @(@("py", "-3.12"), @("python"))) {
    try {
        $v = & $c[0] @($c[1..9] + @("-c", "import sys,struct;print('%d.%d %d' % (sys.version_info[0], sys.version_info[1], struct.calcsize('P')*8))")) 2>$null
        if ($v -eq "3.12 64") { $py = $c; break }
    } catch { }
}
if (-not $py) { throw "serve Python 3.12 a 64 bit (https://www.python.org/downloads/windows/)" }
Write-Host "Python: $($py -join ' ')"
# Node.js is NOT needed (neither for the build nor for the app): without it the tests check that static\app.js is
# byte-identical to the file approved by "node --check" on the Mac (packaging\js_verificato.json, made by crea_kit.py).
$node = Get-Command node -ErrorAction SilentlyContinue
if ($node) { Write-Host "Node.js trovato: controllo JavaScript con node --check" }
elseif (Test-Path "packaging\js_verificato.json") { Write-Host "Node.js non installato (non serve): app.js confrontato con l'impronta verificata sul Mac" }
else { throw "manca packaging\js_verificato.json: usa un kit creato sul Mac con packaging\crea_kit.py (oppure installa Node.js)" }

Step "2. ambiente Python separato (.venv-win)"
if (-not (Test-Path ".venv-win\Scripts\python.exe")) { Run $py[0] (@($py[1..9]) + @("-m", "venv", ".venv-win")) }
$P = Join-Path $Root ".venv-win\Scripts\python.exe"
Run $P @("-m", "pip", "install", "--disable-pip-version-check", "-r", "packaging\requirements-windows.txt")

$env:PYTHONUTF8 = "1"            # same as the packaged program (UTF-8 mode)
if (-not $SenzaTest) {
    Step "3. test automatici (dati inventati, nessuna rete)"
    Run $P @("-m", "pytest", "-q", "-p", "no:cacheprovider")
} else { Write-Host "test saltati su richiesta (-SenzaTest)" }

Step "4. file pubblici e icona"
Run $P @("packaging\prepara_pubblici.py")

Step "5. PyInstaller (cartella unica)"
Run $P @("-m", "PyInstaller", "packaging\nasdaq100_monitor.spec", "--noconfirm", "--clean", "--distpath", "build\dist", "--workpath", "build\work")
$App = Join-Path $Root "build\dist\Nasdaq-100 Monitor"

Step "6. controllo del pacchetto"
$Warn = Join-Path $Root "build\work\nasdaq100_monitor\warn-nasdaq100_monitor.txt"   # PyInstaller missing modules
Run $P @("packaging\verifica_pacchetto.py", $App, "--avvisi", $Warn)

Step "7. prova dell'eseguibile vero"
$args7 = @("packaging\prova_exe.py", (Join-Path $App "Nasdaq-100 Monitor.exe"))
if ($ConInternet) { $args7 += "--con-internet" }
Run $P $args7

Step "8. ZIP e impronta SHA-256"
Run $P @("packaging\crea_zip.py", $App, "build\Nasdaq-100-Monitor-Windows.zip")
Write-Host ""
Write-Host "Fatto: build\Nasdaq-100-Monitor-Windows.zip (impronta in build\Nasdaq-100-Monitor-Windows.zip.sha256.txt)" -ForegroundColor Green
