# shellcheck shell=bash
# Fichiers de l'appliance (copiés dans le système installé) : assemblage de src/rootfs.
# (chargé par build.sh ; ne pas exécuter directement)

gen_rootfs() {
  log "Génération des fichiers de l'appliance"
  R="$W/rootfs"
  rm -rf "$R"; mkdir -p "$R"
  # Contenu de l'appliance : src/rootfs reproduit l'arborescence du système installé (modes : src/rootfs.modes)
  cp -R "$OB_ROOT/src/rootfs/." "$R/"
  find "$R" \( -name '__pycache__' -o -name '*.pyc' -o -name '.DS_Store' \) -prune -exec rm -rf {} +   # jamais de résidus de développement dans l'ISO
  find "$R" -type d -exec chmod 0755 {} +
  find "$R" -type f -exec chmod 0644 {} +
  local mode path
  while read -r mode path; do
    [[ -z $mode || $mode == \#* ]] && continue
    [[ -f $R/$path ]] || die "src/rootfs.modes : fichier absent de src/rootfs : $path"
    chmod "$mode" "$R/$path"
  done < "$OB_ROOT/src/rootfs.modes"

  # Informations de construction (affichées dans « À propos » de l'administration web)
  OB_BUILD_UBUNTU="$UBUNTU_NAME" OB_BUILD_OLLAMA="$OLLAMA_TAG$([[ $INCLUDE_ROCM == 1 ]] && echo ' + ROCm')" \
  OB_BUILD_MODELS="${PRELOADED:-}" OB_VERSION="$OB_VERSION" python3 "$OB_ROOT/lib/py/build_info.py" "$R/etc/ollamabuntu/build-info.json"
  chmod 0644 "$R/etc/ollamabuntu/build-info.json"
  # Liste des logiciels libres (OPEN-SOURCE.md) : système installé + racine de l'ISO
  mkdir -p "$R/usr/share/doc/ollamabuntu"
  python3 "$OB_ROOT/lib/py/open_source_md.py" "$R/usr/local/lib/ollamabuntu/admin/credits.json" "$R/usr/share/doc/ollamabuntu/OPEN-SOURCE.md" "$OB_VERSION"
  chmod 0644 "$R/usr/share/doc/ollamabuntu/OPEN-SOURCE.md"
  cp "$R/usr/share/doc/ollamabuntu/OPEN-SOURCE.md" "$W/iso/OPEN-SOURCE.md"
  # Version dans tous les fichiers
  grep -rl '@@OB_VERSION@@' "$R" | xargs -r sed -i "s/@@OB_VERSION@@/$OB_VERSION/g"
  [[ $OB_LANG == fr || $OB_LANG == en ]] || die "OB_LANG doit valoir fr ou en (reçu : $OB_LANG)"
  printf '%s\n' "$OB_LANG" > "$R/etc/ollamabuntu/lang"; chmod 0644 "$R/etc/ollamabuntu/lang"
  tar --owner=0 --group=0 --numeric-owner -cf "$W/iso/ollamabuntu/rootfs.tar" -C "$R" .
  info "$(tar -tf "$W/iso/ollamabuntu/rootfs.tar" | grep -vc '/$') fichiers"
}
