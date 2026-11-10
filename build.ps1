<#
.SYNOPSIS
    OllamaBuntu - construction de l'ISO sous Windows (Docker Desktop).

.DESCRIPTION
    Construit l'ISO OllamaBuntu (Ubuntu Server + Ollama, installation sans question)
    depuis Windows 10/11, sans Git Bash ni WSL : le script de construction Linux du dépôt
    (build.sh) s'exécute dans un conteneur Ubuntu 24.04 de Docker Desktop.
    Les certificats racines de Windows (proxy d'entreprise qui inspecte le HTTPS) sont
    transmis au conteneur. L'ISO est produite dans le dossier courant.

    Lancement (une fois Docker Desktop démarré) :
        powershell -ExecutionPolicy Bypass -File .\build.ps1

.PARAMETER IsoPath
    ISO Ubuntu Server déjà téléchargée (sinon, téléchargement automatique).
.PARAMETER PreloadModels
    Modèles embarqués dans l'ISO, séparés par des espaces (« » = aucun). Défaut : llama3.2:3b.
.PARAMETER OllamaVersion
    Version d'Ollama (ex. v0.40.14). Défaut : la dernière.
.PARAMETER UbuntuRelease
    Branche Ubuntu Server. Défaut : 24.04.
.PARAMETER Keyboard
    Clavier de la console (ex. fr, us, ch). Défaut : fr.
.PARAMETER KeyboardVariant
    Variante du clavier (ex. latin9).
.PARAMETER Timezone
    Fuseau horaire. Défaut : Europe/Paris.
.PARAMETER Locale
    Langue du système. Défaut : fr_FR.UTF-8.
.PARAMETER GrubTimeout
    Délai du menu de démarrage, en secondes. Défaut : 20.
.PARAMETER IncludeRocm
    Embarque aussi le module AMD ROCm d'Ollama (plusieurs Go).
.PARAMETER ExtraCaCerts
    Fichier PEM de certificats supplémentaires (proxy d'entreprise).
.PARAMETER Language
    Langue des messages et de l'appliance : fr ou en. Défaut : langue de Windows.
.PARAMETER ObVersion
    Numéro de version de l'ISO. Défaut : date et heure (AAAA.MM.JJ-HHMM).

.EXAMPLE
    .\build.ps1
.EXAMPLE
    .\build.ps1 -PreloadModels "" -IsoPath .\ubuntu-24.04.3-live-server-amd64.iso
.EXAMPLE
    .\build.ps1 -PreloadModels "llama3.2:3b qwen3.5:9b" -Keyboard us -Timezone UTC
#>
[CmdletBinding()]
param(
    [Parameter(Position = 0)][string]$IsoPath = "",
    [AllowEmptyString()][string]$PreloadModels,
    [string]$OllamaVersion,
    [string]$UbuntuRelease,
    [string]$Keyboard,
    [string]$KeyboardVariant,
    [string]$Timezone,
    [string]$Locale,
    [int]$GrubTimeout,
    [switch]$IncludeRocm,
    [string]$ExtraCaCerts,
    [string]$ObVersion,
    [ValidateSet('fr', 'en')][string]$Language,
    [ValidateSet('none', 'tpm')][string]$DiskEncryption
)
Set-StrictMode -Version 2.0
$ErrorActionPreference = 'Stop'
try { [Console]::OutputEncoding = New-Object System.Text.UTF8Encoding $false } catch { }

if (-not $Language) { $Language = if ((Get-Culture).TwoLetterISOLanguageName -eq 'fr') { 'fr' } else { 'en' } }
function T([string]$fr, [string]$en) { if ($Language -eq 'en') { $en } else { $fr } }
function Write-Step([string]$m) { Write-Host "==> $m" -ForegroundColor Cyan }
function Write-Info([string]$m) { Write-Host "    $m" }
function Stop-Build([string]$m) { Write-Host ("[" + (T "ERREUR" "ERROR") + "] $m") -ForegroundColor Red; exit 1 }

Write-Step (T "OllamaBuntu : construction de l'ISO sous Windows" "OllamaBuntu: building the ISO on Windows")

# --- 1. Docker Desktop, démarré, en mode « conteneurs Linux »
if (-not (Get-Command docker -ErrorAction SilentlyContinue)) {
    Stop-Build (T "Docker Desktop est nécessaire : https://www.docker.com/products/docker-desktop/`n         Installez-le, démarrez-le, puis relancez ce script." "Docker Desktop is required: https://www.docker.com/products/docker-desktop/`n         Install it, start it, then run this script again.")
}
$osType = (& docker info --format '{{.OSType}}' 2>$null | Out-String).Trim()
if ($LASTEXITCODE -ne 0 -or -not $osType) { Stop-Build (T "Docker est installé mais pas démarré : lancez Docker Desktop, attendez « Engine running », puis relancez." "Docker is installed but not running: start Docker Desktop, wait for “Engine running”, then run again.") }
if ($osType -ne 'linux') { Stop-Build (T "Docker Desktop est en mode « conteneurs Windows » : clic droit sur l'icône Docker > « Switch to Linux containers », puis relancez." "Docker Desktop is in “Windows containers” mode: right-click the Docker icon > “Switch to Linux containers”, then run again.") }
$arch = (& docker info --format '{{.Architecture}}' 2>$null | Out-String).Trim()

# --- 2. Dépôt (dossier de ce script), monté en lecture seule dans le conteneur
$repo = if ($PSScriptRoot) { $PSScriptRoot } else { Split-Path -Parent $MyInvocation.MyCommand.Path }
if (-not (Test-Path -LiteralPath (Join-Path $repo 'build.sh'))) { Stop-Build (T "build.sh introuvable à côté de build.ps1 : dépôt incomplet" "build.sh not found next to build.ps1: incomplete repository") }
$work = (Get-Location).Path
$buildDir = Join-Path $work 'ollamabuntu-build'
$caDir = Join-Path $buildDir 'host-ca'
New-Item -ItemType Directory -Force -Path $caDir | Out-Null

# --- 3. Certificats racines de Windows (proxy d'entreprise qui inspecte le HTTPS)
Get-ChildItem -Path $caDir -Filter *.pem -ErrorAction SilentlyContinue | Remove-Item -Force
$pem = New-Object System.Text.StringBuilder
$count = 0
foreach ($location in 'LocalMachine', 'CurrentUser') {
    try {
        $store = New-Object System.Security.Cryptography.X509Certificates.X509Store ('Root', $location)
        $store.Open('ReadOnly')
        foreach ($c in $store.Certificates) {
            $b64 = [Convert]::ToBase64String($c.RawData, 'InsertLineBreaks') -replace "`r`n", "`n"
            [void]$pem.Append("-----BEGIN CERTIFICATE-----`n$b64`n-----END CERTIFICATE-----`n")
            $count++
        }
        $store.Close()
    } catch { }
}
if ($ExtraCaCerts) {
    if (-not (Test-Path -LiteralPath $ExtraCaCerts)) { Stop-Build (T "ExtraCaCerts introuvable : $ExtraCaCerts" "ExtraCaCerts not found: $ExtraCaCerts") }
    [void]$pem.Append(((Get-Content -LiteralPath $ExtraCaCerts -Raw) -replace "`r`n", "`n"))
    $count += ([regex]::Matches((Get-Content -LiteralPath $ExtraCaCerts -Raw), 'BEGIN CERTIFICATE')).Count
}
$utf8 = New-Object System.Text.UTF8Encoding $false
[System.IO.File]::WriteAllText((Join-Path $caDir 'windows.pem'), $pem.ToString(), $utf8)

# --- 4. ISO source : dans le dossier courant (/work) ou dans un autre dossier (monté à part)
$mounts = @('--mount', "type=bind,source=$work,target=/work",
            '--mount', "type=bind,source=$repo,target=/opt/ollamabuntu,readonly",
            '--mount', "type=bind,source=$caDir,target=/host-ca,readonly")
$scriptArgs = @()
if ($IsoPath) {
    if (-not (Test-Path -LiteralPath $IsoPath -PathType Leaf)) { Stop-Build (T "ISO introuvable : $IsoPath" "ISO not found: $IsoPath") }
    $iso = (Resolve-Path -LiteralPath $IsoPath).Path
    $prefix = $work.TrimEnd('\', '/') + [System.IO.Path]::DirectorySeparatorChar
    if ($iso.StartsWith($prefix, [System.StringComparison]::OrdinalIgnoreCase)) {
        $scriptArgs += '/work/' + ($iso.Substring($prefix.Length) -replace '\\', '/')
    } else {
        $mounts += @('--mount', "type=bind,source=$(Split-Path -Parent $iso),target=/iso-src,readonly")
        $scriptArgs += '/iso-src/' + (Split-Path -Leaf $iso)
    }
}

# --- 5. Paramètres transmis au script de construction
$envs = @('-e', 'OB_IN_CONTAINER=1')
$map = [ordered]@{ PreloadModels = 'PRELOAD_MODELS'; OllamaVersion = 'OLLAMA_VERSION'; UbuntuRelease = 'UBUNTU_RELEASE'; Keyboard = 'KEYBOARD';
                   KeyboardVariant = 'KEYBOARD_VARIANT'; Timezone = 'TIMEZONE'; Locale = 'LOCALE'; GrubTimeout = 'GRUB_TIMEOUT'; ObVersion = 'OB_VERSION' }
foreach ($k in $map.Keys) { if ($PSBoundParameters.ContainsKey($k)) { $envs += @('-e', ('{0}={1}' -f $map[$k], $PSBoundParameters[$k])) } }
if ($IncludeRocm) { $envs += @('-e', 'INCLUDE_ROCM=1') }
$envs += @('-e', "OB_BUILD_LANG=$Language")
if ($PSBoundParameters.ContainsKey('Language')) { $envs += @('-e', "OB_LANG=$Language") }
if ($DiskEncryption) { $envs += @('-e', "DISK_ENCRYPTION=$DiskEncryption") }
foreach ($v in 'HTTP_PROXY', 'HTTPS_PROXY', 'NO_PROXY', 'http_proxy', 'https_proxy', 'no_proxy') {
    $val = [Environment]::GetEnvironmentVariable($v)
    if ($val) { $envs += @('-e', "$v=$val") }
}

$tty = @()
try { if (-not [Console]::IsInputRedirected -and -not [Console]::IsOutputRedirected) { $tty = @('-it') } } catch { }
Write-Info (T "construction dans un conteneur Linux Ubuntu 24.04 ($arch, sans émulation) ; l'ISO produite est une ISO x86-64 (amd64)" "building in an Ubuntu 24.04 Linux container ($arch, no emulation); the produced ISO is an x86-64 (amd64) ISO")
Write-Info (T "dossier de travail : $work" "working folder: $work")
Write-Info (T "certificats racines de Windows transmis au conteneur : $count" "Windows root certificates passed to the container: $count")

$inner = @'
[ "${OB_BUILD_LANG:-fr}" = en ] && echo "    installing tools in the container..." || echo "    installation des outils dans le conteneur..."
apt-get update -qq && DEBIAN_FRONTEND=noninteractive apt-get install -y -qq xorriso curl ca-certificates python3 zstd gpgv ubuntu-keyring >/dev/null \
  || { echo "[ERREUR] installation des outils impossible dans le conteneur" >&2; exit 1; }
if cat /host-ca/*.pem 2>/dev/null | grep -q "BEGIN CERTIFICATE"; then
  cat /host-ca/*.pem | awk '/BEGIN CERTIFICATE/ {n++; f=sprintf("/usr/local/share/ca-certificates/poste-%04d.crt", n)} f {print > f} /END CERTIFICATE/ {close(f); f=""}'
  update-ca-certificates >/dev/null 2>&1 || echo "[!] update-ca-certificates a échoué" >&2
fi
exec bash /opt/ollamabuntu/build.sh "$@"
'@ -replace "`r`n", "`n"

$started = Get-Date
& docker run --rm @tty @mounts -w /work @envs ubuntu:24.04 bash -c $inner _ @scriptArgs
$rc = $LASTEXITCODE
if ($rc -ne 0) { Stop-Build (T "la construction a échoué (code $rc) : voir les messages ci-dessus" "the build failed (code $rc): see the messages above") }

# --- 6. Résultat
$isoOut = Get-ChildItem -Path $work -Filter 'ollamabuntu-*-amd64.iso' | Where-Object { $_.LastWriteTime -ge $started } | Sort-Object LastWriteTime -Descending | Select-Object -First 1
if ($isoOut) {
    $hash = (Get-FileHash -Algorithm SHA256 -LiteralPath $isoOut.FullName).Hash.ToLower()
    Write-Step ((T "Terminé : {0} ({1:N1} Go)" "Done: {0} ({1:N1} GB)") -f $isoOut.FullName, ($isoOut.Length / 1GB))
    Write-Info (T "SHA-256 : $hash" "SHA-256: $hash")
    Write-Info (T "clé USB : Rufus en mode « DD » ou balenaEtcher ; VMware : montez l'ISO comme CD-ROM" "USB key: Rufus in “DD” mode or balenaEtcher; VMware: mount the ISO as a CD-ROM")
}
exit 0
