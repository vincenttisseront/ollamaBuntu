#!/bin/bash
# Retour arrière : restauration d'une sauvegarde de mise à jour dans une racine factice.
set -u
cd "$(dirname "$0")/../.."
RB=$PWD/src/rootfs/usr/local/lib/ollamabuntu/rollback.sh
n=0
ok() { n=$((n+1)); if eval "$1"; then printf '[%02d] OK   - %s\n' "$n" "$2"; else printf '[%02d] ÉCHEC - %s\n' "$n" "$2"; exit 1; fi; }
R=$(mktemp -d); trap 'rm -rf "$R"' EXIT
export OB_ROOT=$R OB_NO_SERVICES=1 TMPDIR=$R
mkdir -p "$R/usr/local/lib/ollamabuntu/admin" "$R/etc/ollamabuntu" "$R/var/backups/ollamabuntu" "$R/var/tmp" "$R/usr/local/sbin" "$R/boot"
# ancienne version -> sauvegarde ; version courante = nouvelle
echo "ancienne console" > "$R/usr/local/lib/ollamabuntu/admin/server.py"; echo "1" > "$R/usr/local/lib/ollamabuntu/old-only.txt"
echo "2026.11.06-1509" > "$R/etc/ollamabuntu/version"; echo "script ancien" > "$R/usr/local/sbin/ollamabuntu-update"
echo "OLLAMA_NUM_PARALLEL=1" > "$R/etc/ollamabuntu/ollama.env"
tar -czf "$R/var/backups/ollamabuntu/appliance-2026.11.06-1509-20261110-105500.tar.gz" -C "$R" usr/local/lib/ollamabuntu usr/local/sbin/ollamabuntu-update etc/ollamabuntu/version etc/ollamabuntu/ollama.env
echo "nouvelle console" > "$R/usr/local/lib/ollamabuntu/admin/server.py"; rm "$R/usr/local/lib/ollamabuntu/old-only.txt"; echo "nouveau fichier" > "$R/usr/local/lib/ollamabuntu/new-only.txt"
echo "2026.11.10-1055" > "$R/etc/ollamabuntu/version"; echo "script neuf" > "$R/usr/local/sbin/ollamabuntu-update"
echo "OLLAMA_NUM_PARALLEL=4" > "$R/etc/ollamabuntu/ollama.env"   # réglage modifié depuis : ne doit pas être écrasé
printf 'set ob_installed_version="2026.11.10-1055"\n' > "$R/boot/ollamabuntu-installed.cfg"
B="$R/var/backups/ollamabuntu/appliance-2026.11.06-1509-20261110-105500.tar.gz"

bash "$RB" restore /etc/passwd >/dev/null 2>&1; rc=$?; ok '[[ $rc -ne 0 ]]' "fichier hors du dossier des sauvegardes refusé"
bash "$RB" restore "$R/var/backups/ollamabuntu/../ollamabuntu/inexistant.tar.gz" >/dev/null 2>&1; rc=$?; ok '[[ $rc -ne 0 ]]' "sauvegarde inexistante refusée"
echo "pas une archive" > "$R/var/backups/ollamabuntu/appliance-1.0-20260101-000000.tar.gz"
bash "$RB" restore "$R/var/backups/ollamabuntu/appliance-1.0-20260101-000000.tar.gz" >/dev/null 2>&1; rc=$?; ok '[[ $rc -ne 0 ]]' "archive corrompue refusée"
mkdir -p "$R/evil/usr/local/lib/ollamabuntu/admin"; echo x > "$R/evil/usr/local/lib/ollamabuntu/admin/server.py"
tar -czf "$R/var/backups/ollamabuntu/appliance-9.9-20260101-000001.tar.gz" -C "$R/evil" --transform='s|^usr/local/lib/ollamabuntu/admin/server.py|../x/server.py|' usr/local/lib/ollamabuntu/admin/server.py 2>/dev/null
bash "$RB" restore "$R/var/backups/ollamabuntu/appliance-9.9-20260101-000001.tar.gz" >/dev/null 2>&1; rc=$?; ok '[[ $rc -ne 0 ]]' "archive à chemins dangereux refusée"

out=$(bash "$RB" restore "$B" 2>&1); rc=$?
ok '[[ $rc -eq 0 ]]' "retour arrière réussi"
ok '[[ $(cat "$R/usr/local/lib/ollamabuntu/admin/server.py") == "ancienne console" ]]' "console de l'ancienne version restaurée"
ok '[[ -f "$R/usr/local/lib/ollamabuntu/old-only.txt" && ! -e "$R/usr/local/lib/ollamabuntu/new-only.txt" ]]' "dossier de l'appliance identique à l'ancien (fichiers ajoutés par la mise à jour retirés)"
ok '[[ $(cat "$R/etc/ollamabuntu/version") == "2026.11.06-1509" && $(cat "$R/usr/local/sbin/ollamabuntu-update") == "script ancien" ]]' "version et scripts restaurés"
ok '[[ $(cat "$R/etc/ollamabuntu/ollama.env") == "OLLAMA_NUM_PARALLEL=4" ]]' "réglages d'Ollama (ollama.env) conservés, non écrasés"
ok 'grep -q "2026.11.06-1509" "$R/boot/ollamabuntu-installed.cfg"' "version de démarrage corrigée"
ok 'ls "$R"/var/backups/ollamabuntu/appliance-2026.11.10-1055-*.tar.gz >/dev/null 2>&1' "état avant retour sauvegardé (retour annulable)"
ok 'grep -q "retour arrière" "$R/var/lib/ollamabuntu/updates.log"' "retour consigné dans l'historique"
ok '[[ -z $(ls "$R"/var/tmp 2>/dev/null) ]]' "aucun fichier temporaire laissé"
# annulation : retour vers la version neuve
N=$(ls "$R"/var/backups/ollamabuntu/appliance-2026.11.10-1055-*.tar.gz | head -1)
bash "$RB" restore "$N" >/dev/null 2>&1; ok '[[ $(cat "$R/usr/local/lib/ollamabuntu/admin/server.py") == "nouvelle console" && $(cat "$R/etc/ollamabuntu/version") == "2026.11.10-1055" ]]' "annulation du retour : nouvelle version rétablie"
