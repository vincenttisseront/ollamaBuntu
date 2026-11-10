# shellcheck shell=bash
# Paquets Ubuntu embarqués (pare-feu, mises à jour automatiques, chiffrement du disque) : signatures et empreintes vérifiées.
# (chargé par build.sh ; ne pas exécuter directement)

SECURITY_DEBS="nftables libnftables1 libnftnl11 libjansson4 unattended-upgrades python3-apt python-apt-common python3-distro-info distro-info-data lsb-release xz-utils liblzma5"
CRYPT_DEBS="libjose0 jose libluksmeta0 luksmeta libpwquality-common libpwquality1 libpwquality-tools libcrack2 cracklib-runtime wamerican libonig5 libjq1 jq libtss2-mu-4.0.1-0t64 libtss2-tcti-device0t64 libtss2-tcti-swtpm0t64 libtss2-tcti-mssim0t64 libtss2-tcti-libtpms0t64 libtss2-tcti-spi-helper0t64 libtss2-tcti-cmd0t64 libtss2-tctildr0t64 libtss2-sys1t64 libtss2-esys-3.0.2-0t64 libtss2-rc0t64 libtss2-fapi1t64 tpm-udev tpm2-tools dracut-install libcurl3t64-gnutls clevis clevis-luks clevis-tpm2 clevis-initramfs"

fetch_security_debs() {
  local kr=/usr/share/keyrings/ubuntu-archive-keyring.gpg dir
  log "Paquets de sécurité à embarquer (pare-feu, mises à jour automatiques)"
  case $UBUNTU_RELEASE in
    22.04*) UBUNTU_CODENAME=jammy ;;
    24.04*) UBUNTU_CODENAME=noble ;;
    *) UBUNTU_CODENAME=$(xorriso -indev "$SRC_ISO" -lsd '/dists/*' 2>/dev/null | grep -oE "/dists/[a-z]+'?$" | grep -oE "[a-z]+" | grep -vE "^(dists|stable)$" | head -n1 || true) ;;
  esac
  if [[ -z ${UBUNTU_CODENAME:-} ]]; then
    warn "nom de code de la version Ubuntu inconnu : paquets non embarqués"
    return 0
  fi
  dir="$W/cache/debs-$UBUNTU_CODENAME"
  if ! command -v gpgv >/dev/null || [[ ! -f $kr ]]; then
    warn "gpgv ou le trousseau Ubuntu absent : paquets non embarqués (le pare-feu dépendra des paquets du système installé)"
    return 0
  fi
  mkdir -p "$dir"
  local comps=main extra=""
  if [[ $DISK_ENCRYPTION != none ]]; then comps="main universe"; extra=$CRYPT_DEBS; info "chiffrement du disque : paquets clevis et TPM2 (archive universe) ajoutés"; fi
  if ! OB_COMPONENTS="$comps" python3 "$OB_ROOT/lib/py/fetch_debs.py" "$dir" "$UBUNTU_MIRROR" "$UBUNTU_CODENAME" "$kr" $SECURITY_DEBS $extra
  then
    [[ $DISK_ENCRYPTION == none ]] || die "chiffrement du disque demandé : les paquets clevis et TPM2 n'ont pas pu être téléchargés (voir ci-dessus)"
    warn "paquets de sécurité non embarqués (voir ci-dessus) : l'ISO reste utilisable"
    return 0
  fi
  SECURITY_DEBS_DIR=$dir
}
