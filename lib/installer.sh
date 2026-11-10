# shellcheck shell=bash
# Installation automatique (Subiquity) : fin d'installation, mise à jour d'une appliance existante, fichier autoinstall.
# (chargé par build.sh ; ne pas exécuter directement)

gen_late() {
  install -m 0755 "$OB_ROOT/src/installer/late.sh" "$W/iso/ollamabuntu/late.sh"
  printf '%s\n' "$OB_VERSION" > "$W/iso/ollamabuntu/VERSION"
  printf '%s\n' "$OLLAMA_TAG" > "$W/iso/ollamabuntu/OLLAMA_VERSION"
  printf '%s\n' "$OB_LANG" > "$W/iso/ollamabuntu/LANG"
}

gen_update() {
  install -m 0755 "$OB_ROOT/src/installer/update.sh" "$W/iso/ollamabuntu/update.sh"
  install -m 0644 "$OB_ROOT/src/installer/autoinstall-update.yaml" "$W/iso/autoinstall-update.yaml"
}

gen_autoinstall() {
  local f="$W/iso/autoinstall.yaml"
  mkdir -p "$W/iso/ollamabuntu"
  rm -f "$W/iso/ollamabuntu/crypt-enabled" "$W/iso/ollamabuntu/crypt-temp"
  CRYPT_TEMP_PASS=""
  if [[ $DISK_ENCRYPTION != none ]]; then   # phrase provisoire de l'installation : aléatoire, propre à cette ISO, supprimée à la fin de l'installation
    CRYPT_TEMP_PASS=$(python3 -c 'import secrets,string; print("".join(secrets.choice(string.ascii_letters + string.digits) for _ in range(24)))')
    printf '%s\n' "$CRYPT_TEMP_PASS" > "$W/iso/ollamabuntu/crypt-temp"; chmod 0600 "$W/iso/ollamabuntu/crypt-temp"
    echo "$DISK_ENCRYPTION" > "$W/iso/ollamabuntu/crypt-enabled"
    info "disque chiffré (LUKS2) : phrase provisoire générée pour cette ISO, supprimée à la fin de l'installation"
  fi
  {
    echo "# OllamaBuntu $OB_VERSION - installation automatique (Subiquity)"
    echo "# Aucune question pendant l'installation : réseau, nom de machine, identifiant"
    echo "# et mot de passe sont demandés par l'assistant console à la fin de l'installation."
    echo "version: 1"
    echo "locale: $LOCALE"
    echo "keyboard:"
    echo "  layout: $KEYBOARD"
    [[ -n $KEYBOARD_VARIANT ]] && echo "  variant: $KEYBOARD_VARIANT"
    echo "timezone: $TIMEZONE"
    echo "refresh-installer:"
    echo "  update: false"
    echo "source:"
    [[ -n $SOURCE_ID ]] && echo "  id: $SOURCE_ID"
    echo "  search_drivers: false"
    echo "apt:"
    echo "  geoip: false"
    echo "  fallback: offline-install"
    echo "storage:"
    echo "  layout:"
    echo "    name: lvm"
    [[ $DISK_ENCRYPTION != none ]] && echo "    password: \"$CRYPT_TEMP_PASS\""
    echo "    sizing-policy: all"
    echo "    match:"
    echo "      size: largest"
    echo "ssh:"
    echo "  install-server: true"
    echo "  allow-pw: true"
    echo "updates: security"
    echo "user-data:"
    echo "  users: []"
    echo "late-commands:"
    echo "  - bash /cdrom/ollamabuntu/late.sh"
    echo "shutdown: reboot"
  } > "$f"
  if python3 -c 'import yaml' 2>/dev/null; then
    python3 "$OB_ROOT/lib/py/check_autoinstall.py" "$f" ${CRYPT_TEMP_PASS:+encrypted} || die "autoinstall.yaml invalide"
  fi
}
