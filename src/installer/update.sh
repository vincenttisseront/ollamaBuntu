#!/bin/bash
# =============================================================================
#  OllamaBuntu - mise à jour d'une appliance existante
#    --live                 depuis l'ISO démarrée (entrée « Mettre à jour » du menu) :
#                           retrouve le système installé, le met à jour, redémarre
#    --target / [--source DIR] [--cleanup-mount DIR]
#                           sur le système en marche (ollamabuntu-update)
#    (mise à jour en ligne : updater.py prépare --source avec l'archive téléchargée, vérifiée et le fichier ONLINE)
#  Conservé : comptes, réseau, nom de machine, certificats, réglages d'Ollama,
#  modèles, données d'Open WebUI. Sauvegarde préalable dans /var/backups/ollamabuntu.
# =============================================================================
set -Eeuo pipefail
export PATH=/usr/sbin:/usr/bin:/sbin:/bin
unset PYTHONPATH PYTHONHOME LD_LIBRARY_PATH LD_PRELOAD 2>/dev/null || true

SRC="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
MODE="" T="" CLEANUP=""
while (($#)); do
  case $1 in
    --live) MODE=live ;;
    --target) MODE=inplace; T=$2; shift ;;
    --source) SRC=$2; shift ;;
    --cleanup-mount) CLEANUP=$2; shift ;;
    *) echo "option inconnue : $1" >&2; exit 2 ;;
  esac
  shift
done
[[ -n $MODE ]] || { echo "usage : $0 --live | --target / [--source DIR]" >&2; exit 2; }
NEW_VERSION=$(cat "$SRC/VERSION" 2>/dev/null || echo "?")
NEW_OLLAMA=$(cat "$SRC/OLLAMA_VERSION" 2>/dev/null || echo "?")
LOG=/tmp/ollamabuntu-update.log
MOUNTED=()

# --- affichage : console dédiée (tty8) en mode ISO, plus la console série éventuelle
exec 3>/dev/null 4>/dev/null
exec 5>&1   # affichage réservé : jamais mélangé aux données (tubes vers tar)
if [[ $MODE == live ]]; then
  if [[ -w /dev/tty8 ]]; then exec 3>/dev/tty8; chvt 8 2>/dev/null || true; printf '\033[2J\033[H' >&3; fi
  ser=$(grep -o 'console=ttyS[0-9]*' /proc/cmdline 2>/dev/null | tail -n1 | cut -d= -f2 || true)
  [[ -n $ser && -w /dev/$ser ]] && exec 4>"/dev/$ser"
fi
# Langue : celle de l'ISO, puis celle du serveur une fois identifié. Traducteur et catalogue de la NOUVELLE
# version, extraits de l'archive (les anciennes versions installées n'en ont pas forcément).
UPD_LANG=$(cat "$SRC/LANG" 2>/dev/null || echo fr)
UPD_I18N=/tmp/ob-update-i18n
mkdir -p "$UPD_I18N" && tar -xf "$SRC/rootfs.tar" -C "$UPD_I18N" ./usr/local/lib/ollamabuntu/i18n.py ./usr/local/lib/ollamabuntu/admin/web/i18n/en.json 2>/dev/null || true
tr_upd() {
  if [[ $UPD_LANG != fr && -f $UPD_I18N/usr/local/lib/ollamabuntu/i18n.py ]] && command -v python3 >/dev/null; then
    OB_I18N_DIR=$UPD_I18N/usr/local/lib/ollamabuntu/admin/web/i18n python3 "$UPD_I18N/usr/local/lib/ollamabuntu/i18n.py" "$UPD_LANG" "$1" 2>/dev/null || printf '%s' "$1"
  else printf '%s' "$1"; fi
}
say() { local m; m="[$(date +%T)] $(tr_upd "$*")"; echo "$m" | tee -a "$LOG"; printf '%s\r\n' "$m" >&3; printf '%s\r\n' "$m" >&4; }
banner() { say ""; say "==================================================================="; say "  $*"; say "==================================================================="; }

cleanup() {
  local i
  for ((i = ${#MOUNTED[@]} - 1; i >= 0; i--)); do umount -l "${MOUNTED[i]}" 2>/dev/null || true; done
  if [[ -n $CLEANUP ]]; then umount -l "$CLEANUP" 2>/dev/null || true; rmdir "$CLEANUP" 2>/dev/null || true; fi
}
fail() {
  banner "ÉCHEC DE LA MISE À JOUR"
  say "$*"
  [[ -n ${BACKUP:-} ]] && say "Sauvegarde des fichiers de l'appliance : ${BACKUP#"$T"}"
  say "Journal : $LOG"
  [[ $MODE == live ]] && say "Le serveur ne redémarre pas automatiquement : notez ce message, puis Ctrl+Alt+Suppr."
  cleanup
  exit 1
}
trap 'fail "ligne $LINENO : $BASH_COMMAND"' ERR

in_t() { if [[ $T == / ]]; then "$@"; else chroot "$T" "$@"; fi; }

# --- mode ISO : retrouver le système installé ------------------------------------
luks_hint() {   # un système chiffré ne se voit pas depuis l'ISO : indiquer la marche à suivre
  if lsblk -rno FSTYPE 2>/dev/null | grep -qx crypto_LUKS; then
    printf ' ; un volume chiffré (LUKS) a été détecté : démarrez le serveur, puis mettez à jour depuis Système > Mises à jour ou le menu console'
  fi
}
find_target() {
  local dev fstype probe=/run/ob-probe found=()
  vgchange -ay >/dev/null 2>&1 || true
  mkdir -p "$probe"
  while read -r dev; do
    # type lu directement sur le périphérique (indépendant de la base udev)
    fstype=$(blkid -p -s TYPE -o value "$dev" 2>/dev/null || true)
    case $fstype in ext4|ext3|xfs|btrfs) ;; *) continue ;; esac
    mount -o ro "$dev" "$probe" 2>/dev/null || continue
    # appliance OllamaBuntu, y compris les toutes premières versions
    if [[ -d $probe/etc/ollamabuntu && ( -f $probe/etc/ollamabuntu/version || -x $probe/usr/local/sbin/ollamabuntu-setup ) ]]; then found+=("$dev"); fi
    umount "$probe" 2>/dev/null || true
  done < <(lsblk -rnpo NAME 2>/dev/null)
  ((${#found[@]} == 1)) || fail "$( ((${#found[@]})) && echo "plusieurs systèmes OllamaBuntu trouvés (${found[*]}) : mise à jour annulée par prudence" || echo "aucun système OllamaBuntu trouvé sur les disques de ce serveur$(luks_hint)")"
  ROOT_DEV=${found[0]}
  T=/run/ob-target
  mkdir -p "$T"
  mount "$ROOT_DEV" "$T"; MOUNTED+=("$T")
  local d
  for d in dev proc sys run; do mkdir -p "$T/$d"; mount --bind "/$d" "$T/$d"; MOUNTED+=("$T/$d"); done
  for d in /boot /boot/efi; do
    if awk -v m="$d" '$1 !~ /^#/ && $2 == m' "$T/etc/fstab" | grep -q .; then
      chroot "$T" mount "$d" && MOUNTED+=("$T$d") || fail "impossible de monter $d du système installé"
    fi
  done
}

# Lecture d'un champ JSON simple ; fichier absent (premières installations) = valeur vide.
# Sans tube : avec « set -o pipefail », sed | head échouait quand le fichier manquait.
# --- affichage de l'avancement -------------------------------------------------------
STEP=0 STEPS=7 T0=$(date +%s) STEP_T0=0
dur() { local s=$1; ((s >= 60)) && printf '%d min %02d s' $((s / 60)) $((s % 60)) || printf '%d s' "$s"; }
step() {   # step TITRE : étape numérotée, avec la durée de l'étape précédente
  local now; now=$(date +%s)
  ((STEP > 0)) && say "      (terminé en $(dur $((now - STEP_T0))))"
  STEP=$((STEP + 1)) STEP_T0=$now
  say "[$STEP/$STEPS] $*"
}
heartbeat() {   # signe de vie pendant une opération sans progression mesurable
  local label=$1 start; start=$(date +%s)
  while sleep "${OB_HEARTBEAT:-15}"; do say "      ... $label : en cours depuis $(dur $(($(date +%s) - start)))" >&5; done
}
run_long() {   # run_long LIBELLÉ COMMANDE... : exécute avec signe de vie, conserve le code de retour
  local label=$1 hb rc=0; shift
  heartbeat "$label" & hb=$!
  "$@" || rc=$?
  kill "$hb" 2>/dev/null; wait "$hb" 2>/dev/null || true
  return "$rc"
}
read_progress() {   # read_progress FICHIER LIBELLÉ : contenu du fichier sur la sortie, progression affichée
  if command -v python3 >/dev/null; then
    python3 - "$1" "$2" "${OB_PROGRESS_INTERVAL:-3}" 2> >(while IFS= read -r l; do say "$l" >&5; done) <<'PY'
import os, sys, time
path, label, every = sys.argv[1], sys.argv[2], float(sys.argv[3])
total, done, t0 = os.path.getsize(path), 0, time.time()
last = t0                      # première mesure après l'intervalle
small = total < 20e6           # petits fichiers : bilan final seulement
fmt = lambda n: ("%.1f Go" % (n / 1e9)).replace(".", ",") if n >= 1e9 else ("%d Mo" % (n / 1e6) if n >= 1e6 else "%d Ko" % (n / 1e3))
out = sys.stdout.buffer
with open(path, "rb") as f:
    while True:
        b = f.read(4 << 20)
        if not b:
            break
        out.write(b); done += len(b)
        now = time.time()
        if not small and now - last >= every:
            last, el = now, max(now - t0, 0.001)
            rate = done / el
            rest = (total - done) / rate if rate else 0
            sys.stderr.write("      %s : %d %% (%s / %s), %s/s, environ %s restantes\n" % (
                label, done * 100 // max(total, 1), fmt(done), fmt(total), fmt(rate), ("%d s" % rest) if rest < 90 else ("%d min" % (rest // 60 + 1))))
            sys.stderr.flush()
out.flush()
sys.stderr.write("      %s : 100 %% (%s) en %d s\n" % (label, fmt(total), time.time() - t0))
PY
  else
    cat -- "$1"
  fi
}

merge_build_info() {   # mise à jour en ligne : le socle Ubuntu et les modèles embarqués restent ceux de l'installation d'origine
  [[ -n $1 && -f $T/etc/ollamabuntu/build-info.json ]] || return 0
  OLD_BI=$1 BI=$T/etc/ollamabuntu/build-info.json python3 - <<'PY' >>"$LOG" 2>&1
import json, os
new = json.load(open(os.environ["BI"], encoding="utf-8"))
old = json.loads(os.environ["OLD_BI"])
for k in ("ubuntu", "models"):
    if old.get(k):
        new[k] = old[k]
new["online"] = True
open(os.environ["BI"], "w", encoding="utf-8").write(json.dumps(new, ensure_ascii=False, indent=1) + "\n")
PY
  grep -q '"online": true' "$T/etc/ollamabuntu/build-info.json" || say "      avertissement : informations de construction non fusionnées (voir $LOG)"
}

json_field() {
  [[ -f $2 ]] || return 0
  local v
  v=$(sed -n "s/.*\"$1\": *\"\([^\"]*\)\".*/\1/p" "$2" 2>/dev/null) || v=""
  printf '%s' "${v%%$'\n'*}"
}

# --- mise à jour ----------------------------------------------------------------------
apply_update() {
  local old old_ollama stamp avail need f
  old=$(cat "$T/etc/ollamabuntu/version" 2>/dev/null || echo "?")
  old_ollama=$(json_field ollama "$T/etc/ollamabuntu/build-info.json"); old_ollama=${old_ollama%% *}
  banner "OllamaBuntu : mise à jour $old -> $NEW_VERSION"
  [[ -f $SRC/rootfs.tar ]] || fail "support de mise à jour incomplet (rootfs.tar absent)"
  say "Système : ${ROOT_DEV:-$T} - Ollama installé : ${old_ollama:-?}, Ollama de l'ISO : $NEW_OLLAMA"
  say "Comptes, réseau, certificats, réglages, modèles et données sont conservés. Ne pas éteindre le serveur."

  step "Vérification de l'espace disque"
  avail=$(df -Pk "$T/usr" | awk 'NR==2 {print $4}')
  need=$((1024 * 1024))
  for f in "$SRC"/ollama-linux-*.tar.* "$SRC"/ollama-linux-*.tgz; do [[ -f $f ]] && need=$((need + $(stat -c %s "$f") * 2 / 1024)); done
  [[ -f $SRC/models.tar ]] && need=$((need + $(stat -c %s "$SRC/models.tar") / 1024))
  ((avail > need)) || fail "espace disque insuffisant : $((avail / 1024)) Mo libres, $((need / 1024)) Mo nécessaires"
  say "      $((avail / 1024)) Mo libres, $((need / 1024)) Mo nécessaires"

  step "Sauvegarde des fichiers de l'appliance (retour arrière possible)"
  stamp=$(date +%Y%m%d-%H%M%S)
  mkdir -p "$T/var/backups/ollamabuntu"
  BACKUP="$T/var/backups/ollamabuntu/appliance-$old-$stamp.tar.gz"
  run_long "sauvegarde" tar -czf "$BACKUP" -C "$T" --ignore-failed-read usr/local/lib/ollamabuntu usr/local/sbin/ollamabuntu-setup \
    usr/local/sbin/ollamabuntu-update usr/local/bin/ollamabuntu-menu etc/systemd/system/ollama.service \
    etc/systemd/system/ollamabuntu-admin.service etc/systemd/system/ollamabuntu-firstboot@.service \
    etc/ollamabuntu/version etc/ollamabuntu/build-info.json etc/ollamabuntu/ollama.env 2>/dev/null || true
  say "      ${BACKUP#"$T"}"

  if [[ $MODE == inplace ]]; then systemctl stop ollama.service 2>/dev/null || true; fi

  step "Fichiers de l'appliance (configuration locale conservée)"
  local bi_old=""
  if [[ -f $SRC/ONLINE && -f $T/etc/ollamabuntu/build-info.json ]]; then bi_old=$(cat "$T/etc/ollamabuntu/build-info.json"); fi
  read_progress "$SRC/rootfs.tar" "fichiers de l'appliance" | tar -xpf - -C "$T" --numeric-owner --no-overwrite-dir \
    --exclude=./etc/ollamabuntu/ollama.env --exclude=./etc/ollamabuntu/lang --exclude=./etc/issue
  if [[ -f $SRC/ONLINE ]]; then merge_build_info "$bi_old"; fi
  if [[ -d $SRC/debs ]]; then   # paquets de sécurité embarqués (posés par postinstall s'ils manquent)
    mkdir -p "$T/var/cache/ollamabuntu/debs"
    cp -f "$SRC"/debs/*.deb "$T/var/cache/ollamabuntu/debs/"
  fi

  if [[ $NEW_OLLAMA != "$old_ollama" || ! -x $T/usr/local/bin/ollama ]]; then
    step "Ollama : $old_ollama -> $NEW_OLLAMA"
    if compgen -G "$T/usr/local/lib/ollama/rocm*" >/dev/null && ! compgen -G "$SRC/ollama-linux-amd64-rocm.*" >/dev/null; then
      say "      module ROCm retiré (lié à l'ancienne version) : réinstallez-le depuis l'onglet GPU"
    fi
    rm -rf "$T/usr/local/lib/ollama"
    mkdir -p "$T/usr/local/bin" "$T/usr/local/lib/ollama"
    for f in "$SRC"/ollama-linux-amd64.tar.zst "$SRC"/ollama-linux-amd64.tgz "$SRC"/ollama-linux-amd64-rocm.tar.zst "$SRC"/ollama-linux-amd64-rocm.tgz; do
      [[ -f $f ]] || continue
      case $f in
        *.tar.zst) read_progress "$f" "Ollama ($(basename "$f"))" | { if command -v zstd >/dev/null; then zstd -dc; else in_t zstd -dc; fi; } | tar -xf - -C "$T/usr/local" --no-same-owner ;;
        *.tgz) read_progress "$f" "Ollama ($(basename "$f"))" | tar -xzf - -C "$T/usr/local" --no-same-owner ;;
      esac
    done
    [[ -x $T/usr/local/bin/ollama ]] || fail "binaire ollama absent après extraction"
  else
    step "Ollama $NEW_OLLAMA déjà installé : conservé"
  fi

  if [[ -f $SRC/models.tar ]]; then
    step "Modèles embarqués dans l'ISO : ajout / mise à jour (les autres modèles sont conservés)"
    mkdir -p "$T/usr/share/ollama/.ollama/models"
    read_progress "$SRC/models.tar" "modèles" | tar -xf - -C "$T/usr/share/ollama/.ollama/models" --no-same-owner
  else
    step "Modèles : aucun modèle embarqué dans cette ISO, modèles installés conservés"
  fi

  step "Configuration du système (comptes de service, droits, sécurité, services)"
  local pi=(/bin/bash /usr/local/lib/ollamabuntu/postinstall.sh)
  if [[ $T != / ]]; then pi=(chroot "$T" /usr/bin/env -i PATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin LANG=C.UTF-8 SERIAL_TTY="" "${pi[@]}"); else pi=(env -i PATH="$PATH" LANG=C.UTF-8 SERIAL_TTY="" "${pi[@]}"); fi
  # messages de la configuration affichés au fil de l'eau (détail complet dans le journal)
  run_long "configuration" "${pi[@]}" > >(while IFS= read -r l; do echo "$l" >> "$LOG"; [[ $l == "[postinstall] "* ]] && say "      ${l#\[postinstall\] }" >&5; done) 2>&1
  if in_t dpkg-query -W -f='${db:Status-Abbrev}' mesa-vulkan-drivers 2>/dev/null | grep -q '^ii'; then
    in_t setcap cap_perfmon+ep /usr/local/bin/ollama 2>/dev/null || true
  fi

  step "Finalisation (version, bannière de connexion, historique)"
  # bannière : régénérée dans la langue de l'appliance ; à défaut, version corrigée dans la bannière existante
  if ! in_t /usr/local/sbin/ollamabuntu-setup --refresh-issue >>"$LOG" 2>&1 || ! grep -q -- "$NEW_VERSION" "$T/etc/issue" 2>/dev/null; then
    if [[ -f $T/usr/share/ollamabuntu/issue.fr ]]; then cp -f "$T/usr/share/ollamabuntu/issue.fr" "$T/etc/issue"
    else sed -i -E "s/(OllamaBuntu +: v)[0-9][0-9.]*(-[0-9]+)?/\1$NEW_VERSION/" "$T/etc/issue" 2>/dev/null || true; fi
  fi
  echo "OllamaBuntu $NEW_VERSION mis à jour le $(date -Is) (précédemment $old)" > "$T/boot/ollamabuntu-installed"
  enc=""; grep -q 'ob_installed_encrypted="1"' "$T/boot/ollamabuntu-installed.cfg" 2>/dev/null && enc='set ob_installed_encrypted="1"'
  printf 'set ob_installed_version="%s"\n%s\n' "$NEW_VERSION" "$enc" > "$T/boot/ollamabuntu-installed.cfg"
  mkdir -p "$T/var/lib/ollamabuntu"
  printf '%s %s -> %s (Ollama %s -> %s, %s)\n' "$(date -Is)" "$old" "$NEW_VERSION" "${old_ollama:-?}" "$NEW_OLLAMA" "$MODE" >> "$T/var/lib/ollamabuntu/updates.log"
  say "      version installée : $(cat "$T/etc/ollamabuntu/version" 2>/dev/null)"
  say "      (terminé en $(dur $(($(date +%s) - STEP_T0))))"
  say "Durée totale de la mise à jour : $(dur $(($(date +%s) - T0)))"
  cp -f "$LOG" "$T/var/log/ollamabuntu-update.log" 2>/dev/null || true
}

if [[ $MODE == live ]]; then
  banner "OllamaBuntu $NEW_VERSION - mise à jour depuis l'ISO"
  say "Recherche du système OllamaBuntu installé sur les disques..."
  find_target
  UPD_LANG=$(cat "$T/etc/ollamabuntu/lang" 2>/dev/null || echo "$UPD_LANG")
  say "Système trouvé : $ROOT_DEV"
  apply_update
  if [[ -d /sys/firmware/efi/efivars ]] && command -v efibootmgr >/dev/null; then
    n=$(efibootmgr 2>/dev/null | awk 'tolower($0) ~ /ubuntu/ {sub(/^Boot/, "", $1); sub(/\*$/, "", $1); print $1; exit}' || true)
    [[ -n $n ]] && efibootmgr -n "$n" >/dev/null 2>&1 || true
  fi
  banner "Mise à jour terminée : redémarrage dans 10 secondes"
  say "Vous pouvez retirer la clé USB / le CD (sinon le menu démarrera le système à jour)."
  sync; sleep 10; cleanup; sync
  reboot -f
  sleep 30; exit 1   # jamais atteint : par sécurité, l'installeur s'arrête en erreur plutôt que de continuer
else
  [[ $T == / ]] || fail "le mode --target n'accepte que / (système en marche)"
  UPD_LANG=$(cat /etc/ollamabuntu/lang 2>/dev/null || echo "$UPD_LANG")
  apply_update
  say "Redémarrage des services"
  systemctl daemon-reload || true
  sysctl --system >/dev/null 2>&1 || true
  agetty --reload 2>/dev/null || true   # bannière à jour sur les invites de connexion déjà affichées
  systemctl restart ollama.service || true
  systemctl restart ollamabuntu-router.service || true
  systemctl try-restart 'ollamabuntu-llama@*.service' || true   # moteurs llama.cpp (modèles MoE) : reprennent le nouveau code
  systemctl restart ollamabuntu-firewall.service || true
  systemctl reload ssh.service 2>/dev/null || true
  systemctl try-restart ollamabuntu-admin.service || true
  banner "Mise à jour terminée : OllamaBuntu $NEW_VERSION ($(dur $(($(date +%s) - T0))))"
  cleanup
fi
