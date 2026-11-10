#!/bin/bash
# OllamaBuntu - finalisation de l'installation (late-commands de Subiquity).
# Exécuté dans l'environnement de l'installeur ; le système installé est monté sur /target.
set -Eeuo pipefail
export PATH=/usr/sbin:/usr/bin:/sbin:/bin
unset PYTHONPATH PYTHONHOME LD_LIBRARY_PATH LD_PRELOAD 2>/dev/null || true

SRC="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
T="${TARGET_MOUNT_POINT:-/target}"
OB_VERSION="$(cat "$SRC/VERSION" 2>/dev/null || echo inconnue)"
mkdir -p "$T/var/log"
LOG="$T/var/log/ollamabuntu-install.log"
exec > >(tee -a "$LOG") 2>&1
step() { echo "[ollamabuntu] $(date +%T) $*"; }
fail() { echo "[ollamabuntu] ERREUR : $*" >&2; exit 1; }
MOUNTED=()
cleanup() { local i; for ((i = ${#MOUNTED[@]} - 1; i >= 0; i--)); do umount -l "${MOUNTED[i]}" 2>/dev/null || true; done; }
trap cleanup EXIT
trap 'fail "ligne $LINENO : $BASH_COMMAND"' ERR

[[ -d $T/etc && -x $T/bin/bash ]] || fail "système installé introuvable dans $T"
step "OllamaBuntu $OB_VERSION : finalisation de l'installation"

# 1. Espace disque
# archives Ollama : environ x1,7 une fois décompressées ; modèles : x1 ; + 1 Go de marge
payload=0
for f in "$SRC"/ollama-linux-*.tar.* "$SRC"/ollama-linux-*.tgz; do
  [[ -f $f ]] && payload=$((payload + $(stat -c %s "$f") * 2))
done
[[ -f $SRC/models.tar ]] && payload=$((payload + $(stat -c %s "$SRC/models.tar")))
need_kb=$((payload / 1024 + 1024 * 1024))
avail_kb=$(df -Pk "$T/usr" | awk 'NR==2 {print $4}')
step "espace libre : $((avail_kb / 1024)) Mo, nécessaire : $((need_kb / 1024)) Mo"
((avail_kb > need_kb)) || fail "espace disque insuffisant sur le disque cible"

# 2. Fichiers de l'appliance
step "copie des fichiers de l'appliance"
tar -xpf "$SRC/rootfs.tar" -C "$T" --numeric-owner --no-overwrite-dir
if [[ -d $SRC/debs ]]; then   # paquets de sécurité embarqués : posés par postinstall s'ils manquent
  mkdir -p "$T/var/cache/ollamabuntu/debs"
  cp -f "$SRC"/debs/*.deb "$T/var/cache/ollamabuntu/debs/"
fi

# 3. Ollama (binaire + bibliothèques CPU/CUDA, ROCm en option)
unzst() { if command -v zstd >/dev/null 2>&1; then zstd -dc -- "$1"; else chroot "$T" zstd -dc < "$1"; fi; }
rm -rf "$T/usr/local/lib/ollama"
mkdir -p "$T/usr/local/bin" "$T/usr/local/lib/ollama"
for a in "$SRC"/ollama-linux-amd64.tar.zst "$SRC"/ollama-linux-amd64.tgz "$SRC"/ollama-linux-amd64-rocm.tar.zst "$SRC"/ollama-linux-amd64-rocm.tgz; do
  [[ -f $a ]] || continue
  step "extraction de $(basename "$a")"
  case $a in
    *.tar.zst) unzst "$a" | tar -xf - -C "$T/usr/local" --no-same-owner ;;
    *.tgz)     tar -xzf "$a" -C "$T/usr/local" --no-same-owner ;;
  esac
done
[[ -x $T/usr/local/bin/ollama ]] || fail "binaire ollama absent après extraction"

# 4. Modèles préchargés
if [[ -f $SRC/models.tar ]]; then
  step "copie des modèles préchargés"
  mkdir -p "$T/usr/share/ollama/.ollama/models"
  tar -xf "$SRC/models.tar" -C "$T/usr/share/ollama/.ollama/models" --no-same-owner
fi

# 5. Réseau provisoire (DHCP) : remplacé par l'assistant au premier démarrage
mkdir -p "$T/etc/netplan/.ollamabuntu-backup"
for f in "$T"/etc/netplan/*.yaml; do [[ -e $f ]] && mv -f "$f" "$T/etc/netplan/.ollamabuntu-backup/"; done
cat > "$T/etc/netplan/01-ollamabuntu.yaml" <<'EOF'
# OllamaBuntu : configuration provisoire (DHCP sur toutes les cartes filaires),
# remplacée par l'assistant de configuration au premier démarrage.
network:
  version: 2
  renderer: networkd
  ethernets:
    ob-all-en:
      match:
        name: "en*"
      dhcp4: true
      optional: true
    ob-all-eth:
      match:
        name: "eth*"
      dhcp4: true
      optional: true
EOF
chmod 600 "$T/etc/netplan/01-ollamabuntu.yaml"

# 6. Nom de machine provisoire
echo "ollamabuntu" > "$T/etc/hostname"
if grep -q '^127\.0\.1\.1' "$T/etc/hosts" 2>/dev/null; then
  sed -i 's/^127\.0\.1\.1.*/127.0.1.1 ollamabuntu/' "$T/etc/hosts"
else
  echo "127.0.1.1 ollamabuntu" >> "$T/etc/hosts"
fi

# 7. Marqueur lu par le menu de l'ISO (empêche toute réinstallation en boucle)
mkdir -p "$T/boot"
echo "OllamaBuntu $OB_VERSION installé le $(date -Is)" > "$T/boot/ollamabuntu-installed"
printf 'set ob_installed_version="%s"\n' "$OB_VERSION" > "$T/boot/ollamabuntu-installed.cfg"

# 8. Configuration dans le système installé
SERIAL_TTY=$(grep -o 'console=ttyS[0-9]*' /proc/cmdline 2>/dev/null | tail -n1 | cut -d= -f2 || true)
for d in dev proc sys; do
  if ! mountpoint -q "$T/$d"; then mkdir -p "$T/$d"; mount --bind "/$d" "$T/$d"; MOUNTED+=("$T/$d"); fi
done
step "configuration du système installé"
chroot "$T" /usr/bin/env -i PATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin \
  LANG=C.UTF-8 SERIAL_TTY="$SERIAL_TTY" /bin/bash /usr/local/lib/ollamabuntu/postinstall.sh

# 9. UEFI : démarrer sur le disque installé au prochain démarrage
if [[ -f $SRC/crypt-enabled ]]; then
  step "chiffrement du disque : clé de récupération et déverrouillage par TPM"
  chroot "$T" /usr/bin/env -i PATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin LANG=C.UTF-8 \
    /usr/local/sbin/ollamabuntu-crypt setup < "$SRC/crypt-temp" \
    || fail "chiffrement du disque : échec (voir /var/log/ollamabuntu-crypt.log) ; installation interrompue plutôt que de laisser la phrase provisoire de l'ISO active"
  printf 'set ob_installed_encrypted="1"\n' >> "$T/boot/ollamabuntu-installed.cfg"
  crypt_tmp=$(head -n1 "$SRC/crypt-temp")   # la phrase provisoire ne doit pas rester dans les journaux de l'installeur
  grep -rlF -- "$crypt_tmp" "$T/var/log/installer" 2>/dev/null | xargs -r sed -i "s/$crypt_tmp/************/g" || true
  step "disque chiffré : la clé de récupération sera affichée au premier démarrage"
fi

if [[ -d /sys/firmware/efi/efivars ]] && command -v efibootmgr >/dev/null 2>&1; then
  n=$(efibootmgr 2>/dev/null | awk 'tolower($0) ~ /ubuntu/ {sub(/^Boot/, "", $1); sub(/\*$/, "", $1); print $1; exit}' || true)
  if [[ -n $n ]] && efibootmgr -n "$n" >/dev/null 2>&1; then step "UEFI : démarrage suivant sur Boot$n"; fi
fi
step "installation d'OllamaBuntu terminée"
