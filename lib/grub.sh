# shellcheck shell=bash
# Menus GRUB (BIOS + UEFI, sans mode graphique forcé).
# (chargé par build.sh ; ne pas exécuter directement)

entry() {  # entry TITRE ID NOYAU INITRD PARAMS_AVANT PARAMS_APRES
  printf 'menuentry "%s" --id %s {\n\tset gfxpayload=keep\n\tlinux\t%s %s ---%s\n\tinitrd\t%s\n}\n' \
    "$1" "$2" "$3" "$5" "${6:+ $6}" "$4"
}

gen_grub() {
  local m ai="autoinstall subiquity.autoinstallpath=/cdrom/autoinstall.yaml" g="$W/iso/boot/grub/grub.cfg"
  mkdir -p "$W/iso/boot/grub"
  {
    cat <<EOF
# OllamaBuntu $OB_VERSION - menu de demarrage de l'ISO ($UBUNTU_NAME)
# Volontairement sans theme graphique ni mode video impose (compatibilite maximale) ;
# titres en ASCII : le mode texte BIOS ne sait pas afficher les accents.
set default="ob-install"
set timeout=$GRUB_TIMEOUT
set timeout_style=menu

loadfont unicode

set menu_color_normal=white/black
set menu_color_highlight=black/light-gray

EOF
    if [[ -n $BIOS_MODS ]]; then
      # En BIOS, les tables de partitions et ext4 ne sont pas chargées automatiquement
      # (en UEFI elles sont intégrées au GRUB signé, et insmod y serait refusé par Secure Boot).
      printf 'if [ "$grub_platform" = "pc" ]; then\n'
      for m in $BIOS_MODS; do printf '\tinsmod %s\n' "$m"; done
      printf 'fi\n\n'
    fi
    cat <<'EOF'
# Si OllamaBuntu est déjà installé sur un disque de ce serveur, on démarre dessus
# par défaut : la clé USB peut rester branchée sans risque de réinstallation.
set ob_root=""
set ob_boot=""
set ob_installed_version=""
set ob_installed_encrypted=""
if search --no-floppy --file --set=ob_root /ollamabuntu-installed; then
	set ob_boot=""
elif search --no-floppy --file --set=ob_root /boot/ollamabuntu-installed; then
	set ob_boot="/boot"
fi
export ob_root
export ob_boot
if [ -n "$ob_root" ]; then
	if [ -f ($ob_root)$ob_boot/ollamabuntu-installed.cfg ]; then
		source ($ob_root)$ob_boot/ollamabuntu-installed.cfg
	fi
	if [ -z "$ob_installed_version" ]; then
		set ob_installed_version="ancienne"
	fi
	# Version installée plus ancienne que l'ISO : mise à jour par défaut (données conservées).
	# Même version ou plus récente : on démarre simplement le système installé.
	set default="ob-local"
	set timeout=10
	if [ "$ob_installed_encrypted" = "1" ]; then
		set default="ob-local"
	elif [ "$ob_installed_version" = "ancienne" ]; then
		set default="ob-update"
	elif [ "$ob_installed_version" \< "@@ISO_VERSION@@" ]; then
		set default="ob-update"
	fi
EOF
    printf '\tmenuentry "Mettre a jour OllamaBuntu : $ob_installed_version -> %s" --id ob-update {\n\t\tset gfxpayload=keep\n\t\tlinux\t%s autoinstall subiquity.autoinstallpath=/cdrom/autoinstall-update.yaml ---\n\t\tinitrd\t%s\n\t}\n' "$OB_VERSION" "$KERNEL" "$INITRD"
    printf '\tmenuentry "Mettre a jour - console serie ttyS0 115200" --id ob-update-serial {\n\t\tset gfxpayload=keep\n\t\tlinux\t%s autoinstall subiquity.autoinstallpath=/cdrom/autoinstall-update.yaml console=tty0 console=ttyS0,115200n8 ---\n\t\tinitrd\t%s\n\t}\n' "$KERNEL" "$INITRD"
    cat <<'EOF'
	menuentry "Demarrer OllamaBuntu deja installe ($ob_installed_version)" --id ob-local {
		if [ "$grub_platform" = "efi" ]; then
			configfile ($ob_root)$ob_boot/grub/grub.cfg
EOF
    if ((BIOS_CHAIN)); then
      cat <<'EOF'
		else
			regexp --set=1:ob_disk '^([^,]+)' "$ob_root"
			set root=$ob_disk
			chainloader +1
			boot
EOF
    else
      cat <<'EOF'
		else
			configfile ($ob_root)$ob_boot/grub/grub.cfg
EOF
    fi
    cat <<'EOF'
		fi
	}
fi

EOF
    entry "Installer OllamaBuntu   (automatique - EFFACE le plus grand disque)" ob-install "$KERNEL" "$INITRD" "$ai" ""
    entry "Installer OllamaBuntu - affichage de secours (nomodeset)" ob-install-safe "$KERNEL" "$INITRD" "$ai" "nomodeset"
    entry "Installer OllamaBuntu - console serie ttyS0 115200 (IPMI/SOL)" ob-install-serial "$KERNEL" "$INITRD" "$ai" "console=tty0 console=ttyS0,115200n8"
    [[ -n $HWE_KERNEL ]] && entry "Installer OllamaBuntu - noyau HWE (materiel recent)" ob-install-hwe "$HWE_KERNEL" "$HWE_INITRD" "$ai" ""
    cat <<'EOF'
if [ "$grub_platform" = "efi" ]; then
menuentry "Demarrer sur le peripherique suivant" {
	exit 1
}
menuentry "Parametres du firmware UEFI" {
	fwsetup
}
EOF
    if [[ -n $MEMTEST ]]; then
      printf 'else\nmenuentry "Test de la memoire (memtest86+)" {\n\tlinux16 %s\n}\n' "$MEMTEST"
    fi
    echo "fi"
  } > "$g"
  sed -i "s/@@ISO_VERSION@@/$OB_VERSION/g" "$g"
  if [[ $OB_LANG != fr ]]; then   # titres du menu traduits (même catalogue que l'appliance)
    OB_I18N_DIR="$W/rootfs/usr/local/lib/ollamabuntu/admin/web/i18n" python3 "$W/rootfs/usr/local/lib/ollamabuntu/i18n.py" --grub "$OB_LANG" "$g" > "$g.tmp" && mv -f "$g.tmp" "$g"
  fi

  GRUB_MAPS=("$g" /boot/grub/grub.cfg)
  if grep -qxF /boot/grub/x86_64-efi/grub.cfg "$W/iso-files.txt"; then
    mkdir -p "$W/iso/boot/grub/x86_64-efi"; cp "$g" "$W/iso/boot/grub/x86_64-efi/grub.cfg"
    GRUB_MAPS+=("$W/iso/boot/grub/x86_64-efi/grub.cfg" /boot/grub/x86_64-efi/grub.cfg)
  fi
  if grep -qxF /boot/grub/loopback.cfg "$W/iso-files.txt"; then
    local lb="$W/iso/boot/grub/loopback.cfg" isoscan='iso-scan/filename=${iso_path}'
    {
      entry "Installer OllamaBuntu (automatique - EFFACE le plus grand disque)" ob-install "$KERNEL" "$INITRD" "$isoscan $ai" ""
      entry "Installer OllamaBuntu - affichage de secours (nomodeset)" ob-install-safe "$KERNEL" "$INITRD" "$isoscan $ai" "nomodeset"
    } > "$lb"
    GRUB_MAPS+=("$lb" /boot/grub/loopback.cfg)
  fi
}
