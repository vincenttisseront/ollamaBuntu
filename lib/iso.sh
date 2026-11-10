# shellcheck shell=bash
# Construction de l'ISO (structure de démarrage d'origine conservée) et vérifications.
# (chargé par build.sh ; ne pas exécuter directement)

build_iso() {
  log "Construction de l'ISO"
  # Correspondances "fichier local -> chemin dans l'ISO"
  MAPS=("$W/iso/autoinstall.yaml" /autoinstall.yaml
        "$W/iso/ollamabuntu/late.sh" /ollamabuntu/late.sh
        "$W/iso/ollamabuntu/VERSION" /ollamabuntu/VERSION
        "$W/iso/ollamabuntu/OLLAMA_VERSION" /ollamabuntu/OLLAMA_VERSION
        "$W/iso/ollamabuntu/LANG" /ollamabuntu/LANG
        "$W/iso/ollamabuntu/update.sh" /ollamabuntu/update.sh
        "$W/iso/autoinstall-update.yaml" /autoinstall-update.yaml
        "$W/iso/OPEN-SOURCE.md" /OPEN-SOURCE.md
        "$W/iso/ollamabuntu/rootfs.tar" /ollamabuntu/rootfs.tar
        "${GRUB_MAPS[@]}")
  local f
  for f in "${OLLAMA_FILES[@]}"; do
    case $f in
      *-rocm.tar.zst) MAPS+=("$f" /ollamabuntu/ollama-linux-amd64-rocm.tar.zst) ;;
      *-rocm.tgz)     MAPS+=("$f" /ollamabuntu/ollama-linux-amd64-rocm.tgz) ;;
      *.tar.zst)      MAPS+=("$f" /ollamabuntu/ollama-linux-amd64.tar.zst) ;;
      *.tgz)          MAPS+=("$f" /ollamabuntu/ollama-linux-amd64.tgz) ;;
      *) die "format d'archive Ollama non reconnu : $f" ;;
    esac
  done
  [[ -n $MODELS_TAR ]] && MAPS+=("$MODELS_TAR" /ollamabuntu/models.tar)
  local deb
  [[ -f $W/iso/ollamabuntu/crypt-enabled ]] && MAPS+=("$W/iso/ollamabuntu/crypt-enabled" "/ollamabuntu/crypt-enabled" "$W/iso/ollamabuntu/crypt-temp" "/ollamabuntu/crypt-temp")
  for deb in "$W"/iso/ollamabuntu/debs/*.deb; do [[ -f $deb ]] && MAPS+=("$deb" "/ollamabuntu/debs/$(basename "$deb")"); done

  # md5sum.txt (utilisé par la vérification d'intégrité du support)
  if grep -qxF /md5sum.txt "$W/iso-files.txt" && iso_extract "$SRC_ISO" /md5sum.txt "$W/src/md5sum.txt"; then
    info "mise à jour de md5sum.txt"
    local i skip=() p
    for ((i = 1; i < ${#MAPS[@]}; i += 2)); do skip+=("./${MAPS[i]#/}"); done
    printf '%s\n' "${skip[@]}" > "$W/md5-skip.txt"
    awk 'NR==FNR {s[$0]=1; next} !(substr($0, 35) in s)' "$W/md5-skip.txt" "$W/src/md5sum.txt" > "$W/iso/md5sum.txt"
    for ((i = 0; i < ${#MAPS[@]}; i += 2)); do
      p="./${MAPS[i+1]#/}"
      printf '%s  %s\n' "$(md5sum < "${MAPS[i]}" | cut -d' ' -f1)" "$p" >> "$W/iso/md5sum.txt"
    done
    MAPS+=("$W/iso/md5sum.txt" /md5sum.txt)
  fi

  # Espace disque
  local need avail
  need=$(( $(stat -c %s "$SRC_ISO") / 1024 + 1048576 ))
  for ((i = 0; i < ${#MAPS[@]}; i += 2)); do need=$(( need + $(stat -c %s "${MAPS[i]}") / 1024 )); done
  avail=$(df -Pk "$(dirname "$OUTPUT")" | awk 'NR==2 {print $4}')
  ((avail > need)) || die "espace insuffisant pour $OUTPUT : $((need / 1024)) Mo nécessaires, $((avail / 1024)) Mo libres"

  local args=(-indev "$SRC_ISO" -outdev "$OUTPUT" -compliance iso_9660_level=3)
  for ((i = 0; i < ${#MAPS[@]}; i += 2)); do args+=(-map "${MAPS[i]}" "${MAPS[i+1]}"); done
  args+=(-boot_image any replay)
  rm -f "$OUTPUT"
  xorriso "${args[@]}" 2>"$W/xorriso.log" || { tail -n 30 "$W/xorriso.log" >&2; die "xorriso a échoué"; }
}

verify_iso() {
  log "Vérification de l'ISO produite"
  local rep="$W/boot-out.txt" i p
  xorriso -indev "$OUTPUT" -report_el_torito plain 2>/dev/null > "$rep" || true
  xorriso -indev "$OUTPUT" -report_system_area plain 2>/dev/null >> "$rep" || true
  if ((HAS_BIOS)); then grep -Eq 'El Torito boot img :.* BIOS ' "$rep" || die "démarrage BIOS perdu"; fi
  grep -Eq 'El Torito boot img :.* UEFI ' "$rep" || die "démarrage UEFI perdu"
  for p in "MBR" "GPT"; do
    if grep -q "$p" "$W/boot-src.txt" && ! grep -q "$p" "$rep"; then die "structure $p perdue (clé USB non démarrable)"; fi
  done
  info "structure de démarrage conservée (El Torito BIOS + UEFI, MBR/GPT hybride)"
  xorriso -indev "$OUTPUT" -find / -type f 2>/dev/null | sed -n "s/^'\(.*\)'$/\1/p" > "$W/out-files.txt"
  for ((i = 1; i < ${#MAPS[@]}; i += 2)); do
    grep -qxF "${MAPS[i]}" "$W/out-files.txt" || die "fichier absent de l'ISO : ${MAPS[i]}"
  done
  mkdir -p "$W/check"
  for p in /autoinstall.yaml /autoinstall-update.yaml /boot/grub/grub.cfg /ollamabuntu/late.sh /ollamabuntu/update.sh; do
    iso_extract "$OUTPUT" "$p" "$W/check/x" && cmp -s "$W/check/x" "$W/iso$p" || die "contenu inattendu : $p"
  done
  grep -q ' autoinstall ' "$W/iso/boot/grub/grub.cfg" || die "mot-clé autoinstall absent du menu"
  info "fichiers OllamaBuntu présents et identiques"
  (cd "$(dirname "$OUTPUT")" && sha256sum "$(basename "$OUTPUT")" > "$(basename "$OUTPUT").sha256")
}
