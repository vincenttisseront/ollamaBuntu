# shellcheck shell=bash
# Hôte : détection (macOS, Windows, WSL, Linux), exécution dans un conteneur Docker, test en VM QEMU.
# (chargé par build.sh ; ne pas exécuter directement)

host_kind() {   # macos | windows | wsl | linux
  case $(uname -s) in
    Darwin) echo macos ;;
    MINGW*|MSYS*|CYGWIN*) echo windows ;;
    *) if grep -qiE 'microsoft|wsl' /proc/version 2>/dev/null; then echo wsl; else echo linux; fi ;;
  esac
}

host_path() {   # chemin tel que Docker Desktop l'attend (C:\... sous Windows)
  if [[ $(host_kind) == windows ]] && need cygpath; then cygpath -w "$1"; else printf '%s' "$1"; fi
}

to_container_path() {   # chemin hôte -> chemin dans le conteneur (/work = dossier courant)
  local abs
  abs="$(cd "$(dirname "$1")" && pwd)/$(basename "$1")"
  case $abs in
    "$PWD"/*) printf '/work/%s' "${abs#"$PWD"/}" ;;
    *) die "$1 doit se trouver dans le dossier courant ($PWD) pour être visible du conteneur" ;;
  esac
}

run_in_docker() {
  local kind label
  kind=$(host_kind); label=$([[ $kind == windows ]] && echo "Windows" || echo "macOS")
  need docker || die "$label détecté : ce script s'exécute dans un conteneur Linux.
         Installez Docker Desktop$([[ $kind == macos ]] && echo " (ou OrbStack / Colima)"), démarrez-le, puis relancez.$([[ $kind == windows ]] && printf '\n         Autre possibilité : lancer le script depuis WSL2 (Ubuntu).')"
  docker info >/dev/null 2>&1 || die "Docker est installé mais pas démarré : lancez Docker Desktop puis relancez."
  local args=() envs=() a v tty=()
  for a in "$@"; do
    if [[ -f $a ]]; then args+=("$(to_container_path "$a")"); else args+=("$a"); fi
  done
  for v in OB_VERSION UBUNTU_RELEASE OLLAMA_VERSION PRELOAD_MODELS INCLUDE_ROCM LOCALE KEYBOARD KEYBOARD_VARIANT TIMEZONE GRUB_TIMEOUT OB_LANG OB_BUILD_LANG DISK_ENCRYPTION; do
    [[ -n ${!v+x} ]] && envs+=(-e "$v=${!v}")
  done
  [[ -n $OLLAMA_ARCHIVE ]] && envs+=(-e "OLLAMA_ARCHIVE=$(to_container_path "$OLLAMA_ARCHIVE")")
  [[ -n ${WORKDIR_SET:-} || -n $OUTPUT ]] && warn "WORKDIR / OUTPUT ignorés sous $label : tout est produit dans $PWD"
  for v in HTTP_PROXY HTTPS_PROXY NO_PROXY http_proxy https_proxy no_proxy; do
    [[ -n ${!v:-} ]] && envs+=(-e "$v=${!v}")
  done
  # Certificats racines approuvés par le poste (dont celui d'un éventuel proxy d'entreprise
  # qui inspecte le HTTPS), transmis au conteneur qui ne les connaît pas.
  local cadir="$PWD/ollamabuntu-build/host-ca" ncert
  mkdir -p "$cadir"; rm -f "$cadir"/*.pem
  if need security; then
    security find-certificate -a -p /Library/Keychains/System.keychain > "$cadir/system.pem" 2>/dev/null || true
    security find-certificate -a -p /System/Library/Keychains/SystemRootCertificates.keychain > "$cadir/roots.pem" 2>/dev/null || true
    [[ ${MAC_LOGIN_KEYCHAIN_CA:-0} == 1 ]] && security find-certificate -a -p "$HOME/Library/Keychains/login.keychain-db" > "$cadir/login.pem" 2>/dev/null || true
  elif [[ $kind == windows ]] && need powershell.exe; then
    # magasins « Autorités de certification racines de confiance » (ordinateur + utilisateur)
    powershell.exe -NoProfile -NonInteractive -Command '$ErrorActionPreference = "SilentlyContinue"; foreach ($s in "Cert:\LocalMachine\Root", "Cert:\CurrentUser\Root") { Get-ChildItem $s | ForEach-Object { "-----BEGIN CERTIFICATE-----"; [Convert]::ToBase64String($_.RawData, "InsertLineBreaks"); "-----END CERTIFICATE-----" } }' \
      2>/dev/null | tr -d '\r' > "$cadir/windows.pem" || true
  fi
  if [[ -n ${EXTRA_CA_CERTS:-} ]]; then
    [[ -f $EXTRA_CA_CERTS ]] || die "EXTRA_CA_CERTS introuvable : $EXTRA_CA_CERTS"
    cp "$EXTRA_CA_CERTS" "$cadir/extra.pem"
  fi
  ncert=$(cat "$cadir"/*.pem 2>/dev/null | grep -c 'BEGIN CERTIFICATE' || true)
  [[ -t 0 && -t 1 ]] && tty=(-it)
  log "$label détecté : construction dans un conteneur Linux Ubuntu 24.04 ($(uname -m), sans émulation)"
  info "l'ISO produite reste une ISO x86-64 (amd64) pour serveurs"
  info "ISO et cache produits dans : $PWD"
  info "certificats racines du poste transmis au conteneur : ${ncert:-0}"
  local mounts=()
  if [[ $kind == windows ]]; then
    # Git Bash / MSYS2 réécrivent les arguments commençant par « / » (/work deviendrait
    # C:/Program Files/Git/work) : conversion désactivée, chemins Windows via --mount.
    export MSYS_NO_PATHCONV=1 MSYS2_ARG_CONV_EXCL='*'
    mounts=(--mount "type=bind,source=$(host_path "$PWD"),target=/work"
            --mount "type=bind,source=$(host_path "$OB_ROOT"),target=/opt/ollamabuntu,readonly"
            --mount "type=bind,source=$(host_path "$cadir"),target=/host-ca,readonly")
  else
    mounts=(-v "$PWD":/work -v "$OB_ROOT":/opt/ollamabuntu:ro -v "$cadir":/host-ca:ro)
  fi
  # (syntaxe ${t[@]+"${t[@]}"} : compatible avec le bash 3.2 de macOS quand le tableau est vide)
  exec docker run --rm ${tty[@]+"${tty[@]}"} \
    "${mounts[@]}" -w /work \
    -e OB_IN_CONTAINER=1 ${envs[@]+"${envs[@]}"} ubuntu:24.04 \
    bash -c 'echo "    installation des outils dans le conteneur..."
             apt-get update -qq && DEBIAN_FRONTEND=noninteractive apt-get install -y -qq xorriso curl ca-certificates python3 zstd >/dev/null \
               || { echo "[ERREUR] installation des outils impossible dans le conteneur" >&2; exit 1; }
             if cat /host-ca/*.pem 2>/dev/null | grep -q "BEGIN CERTIFICATE"; then
               cat /host-ca/*.pem | awk '"'"'/BEGIN CERTIFICATE/ {n++; f=sprintf("/usr/local/share/ca-certificates/poste-%04d.crt", n)} f {print > f} /END CERTIFICATE/ {close(f); f=""}'"'"'
               update-ca-certificates >/dev/null 2>&1 || echo "[!] update-ca-certificates a échoué" >&2
             fi
             exec bash /opt/ollamabuntu/build.sh "$@"' _ ${args[@]+"${args[@]}"}
}

test_vm() {
  local fw=uefi iso=""
  while (($#)); do case $1 in --bios) fw=bios ;; *) iso=$1 ;; esac; shift; done
  [[ -f $iso ]] || die "usage : $0 --test-vm [--bios] fichier.iso"
  need qemu-system-x86_64 && need qemu-img || die "installez qemu-system-x86 (et ovmf pour l'UEFI)"
  mkdir -p "$WORKDIR"
  local disk="$WORKDIR/test-vm-$fw.qcow2" accel=(-accel tcg) cpu=max fwargs=() code="" c
  [[ -f $disk ]] || qemu-img create -q -f qcow2 "$disk" 64G
  if [[ -w /dev/kvm ]]; then accel=(-enable-kvm); cpu=host; else warn "KVM indisponible : la VM sera très lente"; fi
  if [[ $fw == uefi ]]; then
    for c in /usr/share/OVMF/OVMF_CODE_4M.fd /usr/share/OVMF/OVMF_CODE.fd /usr/share/edk2/ovmf/OVMF_CODE.fd /usr/share/edk2/x64/OVMF_CODE.4m.fd; do
      [[ -f $c ]] && { code=$c; break; }
    done
    [[ -n $code ]] || die "firmware OVMF introuvable (paquet ovmf)"
    [[ -f $WORKDIR/test-vm-vars.fd ]] || cp "${code/CODE/VARS}" "$WORKDIR/test-vm-vars.fd"
    fwargs=(-drive "if=pflash,format=raw,readonly=on,file=$code" -drive "if=pflash,format=raw,file=$WORKDIR/test-vm-vars.fd")
  fi
  log "VM de test ($fw) : console web sur https://localhost:8443/, SSH sur le port 2222"
  qemu-system-x86_64 -name OllamaBuntu-test -machine q35 "${accel[@]}" -cpu "$cpu" -smp 4 -m 8192 "${fwargs[@]}" \
    -drive "id=hd,if=none,file=$disk,format=qcow2" -device virtio-blk-pci,drive=hd,bootindex=1 \
    -drive "id=cd,if=none,media=cdrom,readonly=on,file=$iso" -device ide-cd,drive=cd,bootindex=2 \
    -netdev user,id=n0,hostfwd=tcp::8443-:443,hostfwd=tcp::2222-:22 -device virtio-net-pci,netdev=n0 \
    -vga std
}
