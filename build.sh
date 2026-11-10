#!/usr/bin/env bash
# =============================================================================
#   OllamaBuntu - générateur d'ISO  (Ubuntu Server LTS + Ollama, appliance IA)
# =============================================================================
#   Usage :
#     ./build.sh                      télécharge Ubuntu Server + Ollama
#     ./build.sh ubuntu-24.04.x-live-server-amd64.iso   ISO locale
#     ./build.sh --test-vm [--bios] ollamabuntu.iso     test en VM QEMU
#     ./build.sh --bundle             archive de mise à jour en ligne (release GitHub), sans ISO :
#                                     ollamabuntu-update-<version>.tar.gz + SHA256SUMS (+ .sig si OB_SIGNING_KEY)
#
#   Windows : build.ps1 (PowerShell + Docker Desktop, sans Git Bash ni WSL).
#
#   Systèmes : Linux ou WSL2 (Ubuntu/Debian conseillé). Sous macOS et sous Windows
#   (Git Bash, MSYS2, Cygwin), build.sh se relance automatiquement dans un conteneur
#   Docker Linux (Docker Desktop, OrbStack, Colima).
#
#   Paramètres facultatifs (variables d'environnement) :
#     UBUNTU_RELEASE   24.04            branche Ubuntu Server téléchargée
#     OB_LANG          fr               langue par défaut (fr | en) : menu de démarrage, assistant, console
#     DISK_ENCRYPTION  none             tpm : disque chiffré (LUKS2) ; déverrouillage par TPM2, sinon phrase de passe
#     OLLAMA_VERSION   latest           ou une version précise (ex. v0.40.14)
#     OLLAMA_ARCHIVE   (vide)           archive ollama-linux-amd64.tar.zst déjà téléchargée
#     PRELOAD_MODELS   "llama3.2:3b"    modèles embarqués dans l'ISO ("" = aucun)
#     INCLUDE_ROCM     0                1 = ajoute le support des GPU AMD (~1 Go)
#     LOCALE           fr_FR.UTF-8
#     KEYBOARD         fr               clavier de la console (saisie du mot de passe !)
#     KEYBOARD_VARIANT (vide)           ex. latin9, oss, mac ...
#     TIMEZONE         Europe/Paris
#     GRUB_TIMEOUT     20               secondes avant l'installation automatique
#     WORKDIR          ./ollamabuntu-build
#     OUTPUT           ./ollamabuntu-<version>-amd64.iso
#     OB_SIGNING_KEY   (vide)           --bundle : clé privée Ed25519 (PEM) qui signe SHA256SUMS
#     EXTRA_CA_CERTS   (vide)           certificat racine PEM d'un proxy d'entreprise qui inspecte
#                                       le HTTPS (sous macOS, ceux du trousseau Système sont
#                                       repris automatiquement)
#
#   Déroulé sur le serveur cible :
#     1. démarrage sur l'ISO -> installation 100 % automatique, sans aucune question
#        (Ubuntu Server, Ollama, console d'administration web, modèles embarqués)
#     2. redémarrage -> assistant console : réseau, nom de machine, identifiant,
#        mot de passe ; puis l'appliance est opérationnelle (https://<ip>/).
set -Eeuo pipefail
shopt -s nullglob

OB_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
for _lib in common host prereqs ubuntu ollama packages rootfs installer grub iso bundle; do
  # shellcheck source=/dev/null
  source "$OB_ROOT/lib/$_lib.sh"
done

main() {
  i18n_init
  [[ $DISK_ENCRYPTION == none || $DISK_ENCRYPTION == tpm ]] || die "DISK_ENCRYPTION doit valoir none ou tpm (reçu : $DISK_ENCRYPTION)"
  case "${1:-}" in
    -h|--help) usage; exit 0 ;;
    --test-vm)
      case $(host_kind) in
        macos) die "--test-vm nécessite Linux + KVM. Sur Mac : testez l'ISO dans UTM ou VirtualBox
         (Mac Intel), ou directement sur un serveur / une VM x86 de votre infrastructure." ;;
        windows) die "--test-vm nécessite Linux + KVM. Sous Windows : testez l'ISO dans Hyper-V,
         VMware Workstation ou VirtualBox (VM UEFI, 8 Go de RAM, disque de 64 Go)." ;;
      esac
      shift; test_vm "$@"; exit 0 ;;
  esac
  case $(host_kind) in
    macos|windows) [[ -n ${OB_IN_CONTAINER:-} ]] || run_in_docker "$@" ;;
    wsl) [[ $PWD == /mnt/* ]] && info "WSL : construction sur un disque Windows (/mnt/...) possible mais lente ; ~/ est bien plus rapide" ;;
  esac
  if [[ ${1:-} == --make-ps1 ]]; then
    die "--make-ps1 n'existe plus : le dépôt contient build.ps1 (Windows) et build.sh (Linux, macOS, WSL) ; voir README.md"
  fi
  if [[ ${1:-} == --bundle ]]; then build_bundle; exit 0; fi
  [[ -n ${1:-} ]] && SRC_ISO=$(readlink -f "$1")
  check_deps
  [[ -n $SRC_ISO ]] || fetch_ubuntu_iso
  inspect_iso
  [[ -n $OUTPUT ]] || OUTPUT="$PWD/ollamabuntu-$OB_VERSION-amd64.iso"
  OUTPUT=$(readlink -f "$OUTPUT")
  fetch_ollama
  fetch_security_debs
  [[ $DISK_ENCRYPTION == none || -n ${SECURITY_DEBS_DIR:-} ]] || die "chiffrement du disque demandé : paquets clevis et TPM2 non embarqués"
  preload_models
  rm -rf "$W/iso"; mkdir -p "$W/iso/ollamabuntu"
  if [[ -n ${SECURITY_DEBS_DIR:-} ]]; then
    mkdir -p "$W/iso/ollamabuntu/debs"
    while read -r f; do [[ -n $f ]] && cp "$SECURITY_DEBS_DIR/$f" "$W/iso/ollamabuntu/debs/"; done < "$SECURITY_DEBS_DIR/selection.txt"
  fi
  gen_rootfs
  gen_late
  gen_update
  gen_autoinstall
  gen_grub
  build_iso
  verify_iso
  log "ISO prête : $OUTPUT ($(du -h "$OUTPUT" | cut -f1))"
  info "Ubuntu   : $UBUNTU_NAME"
  info "Ollama   : $OLLAMA_TAG$([[ $INCLUDE_ROCM == 1 ]] && echo ' + ROCm')"
  info "Modèles  : ${PRELOADED:-aucun}"
  info "Clavier  : $KEYBOARD${KEYBOARD_VARIANT:+ ($KEYBOARD_VARIANT)}  - $LOCALE - $TIMEZONE"
  info "SHA-256  : $(cut -d' ' -f1 "$OUTPUT.sha256")"
  echo
  info "Clé USB (Linux) : sudo dd if=$(basename "$OUTPUT") of=/dev/sdX bs=4M status=progress oflag=sync"
  info "Clé USB (Windows) : Rufus en mode « DD » ou balenaEtcher"
  info "Test en VM      : $0 --test-vm $(basename "$OUTPUT")"
}

main "$@"
