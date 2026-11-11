#!/bin/bash
# =============================================================================
#  OllamaBuntu - retour à la version précédente de l'appliance
#    rollback.sh restore /var/backups/ollamabuntu/appliance-<version>-<date>.tar.gz
#  Restaure les fichiers de l'appliance (console, routeur, scripts, services) sauvegardés avant une mise à jour.
#  Conservés tels quels : réglages d'Ollama (ollama.env), comptes, modèles, données. Le binaire Ollama n'est pas
#  rétabli (il reste compatible). Une sauvegarde de l'état actuel est faite d'abord : le retour est lui-même annulable.
#  OB_ROOT (essais) : racine du système ; OB_NO_SERVICES=1 : ne touche pas aux services.
# =============================================================================
set -Eeuo pipefail
export PATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin
ROOT=${OB_ROOT:-}
[[ -n $ROOT || $EUID -eq 0 ]] || exec sudo "$0" "$@"
# copie en mémoire : le dossier de ce script est remplacé pendant l'opération
if [[ ${OB_RB_RELOC:-} != 1 ]]; then
  self=$(mktemp "${TMPDIR:-/run}/ob-rollback.XXXXXX"); cp "$0" "$self"
  OB_RB_RELOC=1 exec /bin/bash "$self" "$@"
fi
trap 'rm -f "$0"' EXIT
say() { echo "[$(date +%T)] $*"; }
die() { say "[ERREUR] $*" >&2; exit 1; }
[[ ${1:-} == restore && -n ${2:-} ]] || die "usage : rollback.sh restore FICHIER"
DIR=$ROOT/var/backups/ollamabuntu
f=$(readlink -f "$2") || die "sauvegarde introuvable"
[[ $f == "$DIR"/appliance-*.tar.gz && -f $f ]] || die "sauvegarde invalide (dossier ou nom inattendu)"
base=$(basename "$f" .tar.gz)
[[ $base =~ ^appliance-(.+)-([0-9]{8}-[0-9]{6})$ ]] || die "nom de sauvegarde inattendu"
old=${BASH_REMATCH[1]}
list=$(tar -tzf "$f") || die "sauvegarde illisible ou corrompue"
if grep -Eq '(^/|(^|/)\.\.(/|$))' <<<"$list"; then die "sauvegarde refusée : chemins dangereux"; fi
grep -q '^usr/local/lib/ollamabuntu/admin/server.py$' <<<"$list" || die "la sauvegarde ne contient pas la console d'administration"
cur=$(cat "$ROOT/etc/ollamabuntu/version" 2>/dev/null || echo "?")
say "Retour de la version $cur à la version $old"

stage=$(mktemp -d "$ROOT/var/tmp/ob-rollback.XXXXXX" 2>/dev/null || mktemp -d)
trap 'rm -rf "$stage"; rm -f "$0"' EXIT
say "[1/4] Lecture de la sauvegarde"
tar -xzpf "$f" -C "$stage" --numeric-owner
[[ -f $stage/usr/local/lib/ollamabuntu/admin/server.py ]] || die "sauvegarde incomplète"

say "[2/4] Sauvegarde de l'état actuel (le retour reste annulable)"
mkdir -p "$DIR"
now="$DIR/appliance-$cur-$(date +%Y%m%d-%H%M%S).tar.gz"
tar -czf "$now" -C "$ROOT" --ignore-failed-read usr/local/lib/ollamabuntu usr/local/sbin/ollamabuntu-setup usr/local/sbin/ollamabuntu-update \
  usr/local/bin/ollamabuntu-menu etc/systemd/system/ollama.service etc/systemd/system/ollamabuntu-admin.service etc/systemd/system/ollamabuntu-firstboot@.service \
  etc/ollamabuntu/version etc/ollamabuntu/build-info.json 2>/dev/null || true
say "      ${now#"$ROOT"}"

say "[3/4] Restauration des fichiers"
lib=$ROOT/usr/local/lib/ollamabuntu
if [[ -d $lib ]]; then mv "$lib" "$lib.rollback-old"; fi
if ! mv "$stage/usr/local/lib/ollamabuntu" "$lib"; then
  [[ -d $lib.rollback-old ]] && mv "$lib.rollback-old" "$lib"
  die "restauration impossible : l'état précédent est conservé"
fi
rm -rf "$lib.rollback-old"
for p in usr/local/sbin/ollamabuntu-setup usr/local/sbin/ollamabuntu-update usr/local/bin/ollamabuntu-menu etc/systemd/system/ollama.service \
         etc/systemd/system/ollamabuntu-admin.service etc/systemd/system/ollamabuntu-firstboot@.service etc/ollamabuntu/version etc/ollamabuntu/build-info.json; do
  if [[ -e $stage/$p ]]; then mkdir -p "$(dirname "$ROOT/$p")"; cp -a "$stage/$p" "$ROOT/$p"; fi
done
if [[ -f $ROOT/boot/ollamabuntu-installed.cfg ]]; then
  sed -i "s/^set ob_installed_version=.*/set ob_installed_version=\"$old\"/" "$ROOT/boot/ollamabuntu-installed.cfg" 2>/dev/null || true
fi
mkdir -p "$ROOT/var/lib/ollamabuntu"
printf '%s %s -> %s (retour arrière)\n' "$(date -Is)" "$cur" "$old" >> "$ROOT/var/lib/ollamabuntu/updates.log"

say "[4/4] Redémarrage des services"
if [[ ${OB_NO_SERVICES:-} != 1 ]]; then
  systemctl daemon-reload || true
  systemctl restart ollamabuntu-router.service || true
  systemctl restart ollamabuntu-firewall.service || true
  systemctl try-restart ollamabuntu-admin.service || true
fi
say "Retour terminé : version $(cat "$ROOT/etc/ollamabuntu/version" 2>/dev/null || echo "$old")"
