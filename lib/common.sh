# shellcheck shell=bash
# Variables de construction, messages, téléchargement.
# (chargé par build.sh ; ne pas exécuter directement)

OB_VERSION="${OB_VERSION:-$(date +%Y.%m.%d-%H%M)}"   # AAAA.MM.JJ-HHMM : comparable par GRUB
UBUNTU_RELEASE="${UBUNTU_RELEASE:-24.04}"
OB_LANG="${OB_LANG:-fr}"                         # langue par défaut de l'appliance : fr | en
DISK_ENCRYPTION="${DISK_ENCRYPTION:-none}"           # none | tpm : disque chiffré (LUKS2), TPM2 si présent, sinon phrase de passe
OLLAMA_VERSION="${OLLAMA_VERSION:-latest}"
OLLAMA_ARCHIVE="${OLLAMA_ARCHIVE:-}"
PRELOAD_MODELS="${PRELOAD_MODELS-llama3.2:3b}"
INCLUDE_ROCM="${INCLUDE_ROCM:-0}"
LOCALE="${LOCALE:-fr_FR.UTF-8}"
KEYBOARD="${KEYBOARD:-fr}"
KEYBOARD_VARIANT="${KEYBOARD_VARIANT:-}"
TIMEZONE="${TIMEZONE:-Europe/Paris}"
GRUB_TIMEOUT="${GRUB_TIMEOUT:-20}"
WORKDIR_SET="${WORKDIR:-}"
WORKDIR="${WORKDIR:-$PWD/ollamabuntu-build}"
OUTPUT="${OUTPUT:-}"

CACHE="$WORKDIR/cache"
W="$WORKDIR/work"
SRC_ISO=""

# ----------------------------------------------------------------------------
#  Utilitaires
# ----------------------------------------------------------------------------
UBUNTU_MIRROR="${UBUNTU_MIRROR:-http://archive.ubuntu.com/ubuntu}"
if [[ -t 1 ]]; then C1=$'\e[1;38;5;208m'; C2=$'\e[1;31m'; C3=$'\e[1;33m'; C0=$'\e[0m'; else C1=""; C2=""; C3=""; C0=""; fi
# Langue des messages : OB_BUILD_LANG, sinon celle de l'appliance (OB_LANG). Traducteur et catalogue
# de l'appliance (src/rootfs) : mêmes traductions, aucune copie à maintenir.
_I18N_PY="$OB_ROOT/src/rootfs/usr/local/lib/ollamabuntu/i18n.py"
_I18N_CAT="$OB_ROOT/src/rootfs/usr/local/lib/ollamabuntu/admin/web/i18n"
_I18N_ON=""
i18n_init() {
  [[ ${OB_BUILD_LANG:-${OB_LANG:-fr}} != fr ]] && command -v python3 >/dev/null && [[ -f $_I18N_PY ]] && _I18N_ON=1
  return 0
}
_t() { if [[ -n $_I18N_ON ]]; then OB_I18N_DIR=$_I18N_CAT python3 "$_I18N_PY" "${OB_BUILD_LANG:-${OB_LANG:-fr}}" "$1" 2>/dev/null || printf '%s' "$1"; else printf '%s' "$1"; fi; }
log()  { printf '%s==>%s %s\n' "$C1" "$C0" "$(_t "$*")"; }
info() { printf '    %s\n' "$(_t "$*")"; }
warn() { printf '%s[!]%s %s\n' "$C3" "$C0" "$(_t "$*")" >&2; }
die()  { printf '%s[%s]%s %s\n' "$C2" "$([[ -n $_I18N_ON ]] && echo ERROR || echo ERREUR)" "$C0" "$(_t "$*")" >&2; exit 1; }
need() { command -v "$1" >/dev/null 2>&1; }
trap 'die "échec à la ligne $LINENO : $BASH_COMMAND"' ERR

usage() { awk 'NR > 1 && /^#/ { sub(/^# ?/, ""); print; next } NR > 1 { exit }' "$0"; }

download() {  # download URL DEST : téléchargement avec reprise et nouvelles tentatives
  local url=$1 dest=$2 rc=0
  mkdir -p "$(dirname "$dest")"
  info "téléchargement : $url"
  curl -fL --retry 5 --retry-delay 3 --connect-timeout 20 --progress-bar -C - -o "$dest.part" "$url" || rc=$?
  if ((rc != 0 && rc != 60)); then
    rc=0; curl -fL --retry 5 --retry-delay 3 --connect-timeout 20 --progress-bar -o "$dest.part" "$url" || rc=$?
  fi
  ((rc == 60)) && cert_error "$url"
  ((rc == 0)) || die "téléchargement impossible : $url"
  mv -f "$dest.part" "$dest"
}

cert_error() {   # certificat HTTPS refusé (curl code 60) : explication et solution
  local mac=""
  [[ -n ${OB_IN_CONTAINER:-} ]] && mac="
         Sous macOS, les certificats du trousseau Système sont déjà repris ; si le vôtre
         est dans votre trousseau de session, relancez avec MAC_LOGIN_KEYCHAIN_CA=1."
  die "certificat HTTPS non reconnu pour $1
         Cause habituelle : proxy d'entreprise qui inspecte le HTTPS (Zscaler, Netskope...).
         Fournissez son certificat racine (fichier PEM, demandez-le à votre équipe IT) :
             EXTRA_CA_CERTS=/chemin/racine-entreprise.pem ./build.sh$mac"
}

sha256_ok() { [[ -f $1 ]] && [[ "$(sha256sum "$1" | cut -d' ' -f1)" == "$2" ]]; }

iso_extract() {  # iso_extract ISO CHEMIN_ISO DEST
  mkdir -p "$(dirname "$3")"
  rm -f "$3"
  xorriso -osirrox on -indev "$1" -extract "$2" "$3" >/dev/null 2>&1 || return 1
  chmod u+w "$3"
}
