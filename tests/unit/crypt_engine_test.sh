#!/bin/bash
set -u
D=/tmp/crypt; E="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)/src/rootfs/usr/local/sbin/ollamabuntu-crypt"; rm -rf $D; mkdir -p $D/tpm $D/state
export OB_CRYPT_STATE=$D/state OB_CRYPT_LOG=$D/crypt.log OB_CRYPT_NO_INITRAMFS=1 OB_CRYPT_PBKDF_ARGS="--pbkdf pbkdf2 --pbkdf-force-iterations 1000" OB_CRYPTTAB=/nonexistent
n=0; ok() { n=$((n+1)); if [ "$1" = 0 ]; then printf '[%02d] OK   - %s\n' $n "$2"; else printf '[%02d] ÉCHEC - %s\n' $n "$2"; pkill -f "[s]wtpm socket" 2>/dev/null; exit 1; fi; }
opens() { printf '%s' "$2" | cryptsetup open --test-passphrase --key-file=- "$1" >/dev/null 2>&1; }
newdisk() { rm -f $D/disk.img; rm -rf $D/state/*; truncate -s 32M $D/disk.img; printf '%s' "$1" | cryptsetup luksFormat --type luks2 --pbkdf pbkdf2 --pbkdf-force-iterations 1000 --batch-mode --key-file=- $D/disk.img; export OB_CRYPT_DEV=$D/disk.img; }
js() { python3 -c "import json,sys; d=json.load(sys.stdin); print(d.get(sys.argv[1]))" "$1"; }
T0="TEMP-installation-ISO-9fK2"; NEWP="phrase de demarrage 2026"
# --- sans TPM
unset TPM2TOOLS_TCTI; newdisk "$T0"
printf '%s\n' "$T0" | $E setup; ok $? "sans TPM : configuration terminée (phrase temporaire fournie par l'entrée standard)"
REC=$(head -n1 $D/state/recovery.key); [[ $REC =~ ^([A-Z2-7]{6}-){8}[A-Z2-7]{4}$ ]]; ok $? "clé de récupération : 256 bits, 9 groupes lisibles « $REC »"
opens $D/disk.img "$REC"; ok $? "la clé de récupération ouvre le volume"
opens $D/disk.img "$T0"; ok $? "sans TPM, la phrase temporaire reste valide jusqu'à l'assistant"
S=$($E status); [[ $(js tpm_bound <<<"$S") == False && $(js passphrase_needed <<<"$S") == True && $(js recovery_pending <<<"$S") == True ]]; ok $? "état : pas de TPM, phrase de démarrage à définir, clé en attente de confirmation"
printf 'court\n' | $E set-passphrase 2>/dev/null; [ $? -ne 0 ]; ok $? "phrase de moins de 12 caractères refusée"
printf '%s\n' "$NEWP" | $E set-passphrase; ok $? "phrase de démarrage définie (authentifiée par la clé de récupération)"
opens $D/disk.img "$NEWP" && ! opens $D/disk.img "$T0"; ok $? "la nouvelle phrase ouvre le volume ; la phrase temporaire de l'ISO est morte"
S=$($E status); [[ $(js passphrase_needed <<<"$S") == False && $(js passphrase_set <<<"$S") == True ]]; ok $? "état : phrase de démarrage définie"
$E ack; [ ! -e $D/state/recovery.key ] && ! $E recovery-show >/dev/null 2>&1; ok $? "confirmation : la copie locale de la clé de récupération est effacée"
opens $D/disk.img "$REC"; ok $? "la clé de récupération reste valable après confirmation"
OUT=$(printf 'mauvaise phrase\n' | $E recovery-new 2>&1); [ $? -ne 0 ] && opens $D/disk.img "$REC"; ok $? "nouvelle clé avec une mauvaise phrase : refusée, ancienne clé intacte"
REC2=$(printf '%s\n' "$NEWP" | $E recovery-new); opens $D/disk.img "$REC2" && ! opens $D/disk.img "$REC" && opens $D/disk.img "$NEWP"; ok $? "nouvelle clé de récupération : l'ancienne est révoquée, la phrase de démarrage reste valable"
# --- avec TPM (logiciel)
swtpm socket --tpm2 --tpmstate dir=$D/tpm --server type=tcp,bindaddr=127.0.0.1,port=2321 --ctrl type=tcp,bindaddr=127.0.0.1,port=2322 --flags not-need-init,startup-clear --daemon --pid file=$D/pid >/dev/null 2>&1 </dev/null; sleep 1
export TPM2TOOLS_TCTI="swtpm:host=127.0.0.1,port=2321"
tpm2_getrandom 4 >/dev/null 2>&1; ok $? "TPM logiciel démarré (swtpm)"
newdisk "$T0"; printf '%s\n' "$T0" | $E setup; ok $? "avec TPM : configuration terminée"
REC=$(head -n1 $D/state/recovery.key); S=$($E status)
[[ $(js tpm_bound <<<"$S") == True && $(js passphrase_needed <<<"$S") == False ]]; ok $? "état : clé liée au TPM, aucune phrase à définir"
opens $D/disk.img "$REC" && ! opens $D/disk.img "$T0"; ok $? "phrase temporaire supprimée dès l'installation ; clé de récupération valable"
CS=$(clevis luks list -d $D/disk.img | awk -F: '/tpm2/ {print $1}'); clevis luks pass -d $D/disk.img -s "$CS" > $D/tp 2>/dev/null; cryptsetup open --test-passphrase --key-file $D/tp $D/disk.img; ok $? "le TPM restitue une clé qui ouvre le volume (déverrouillage automatique)"
REC2=$($E recovery-new </dev/null); opens $D/disk.img "$REC2" && ! opens $D/disk.img "$REC"; ok $? "nouvelle clé de récupération autorisée par le TPM seul (aucune phrase demandée)"
clevis luks pass -d $D/disk.img -s "$CS" > $D/tp 2>/dev/null; cryptsetup open --test-passphrase --key-file $D/tp $D/disk.img; ok $? "le déverrouillage par TPM fonctionne toujours après le changement de clé"
# --- cas d'erreur
newdisk "$T0"; printf '%s\n' "mauvaise-temp" | $E setup 2>/dev/null; [ $? -ne 0 ] && [ ! -e $D/state/recovery.key ] && opens $D/disk.img "$T0" && [ "$(cryptsetup luksDump --dump-json-metadata $D/disk.img | python3 -c 'import json,sys; print(len(json.load(sys.stdin)["keyslots"]))')" = 1 ]; ok $? "mauvaise phrase temporaire : échec net, aucune clé ajoutée, aucun fichier laissé"
newdisk "$T0"; printf '%s\n' "$T0" | OB_CRYPT_PCRS=99 $E setup; [ $? -eq 0 ]; ok $? "liaison TPM impossible (PCR invalide) : l'installation continue"
S=$($E status); [[ $(js tpm_bound <<<"$S") == False && $(js passphrase_needed <<<"$S") == True ]] && [ -z "$(clevis luks list -d $D/disk.img 2>/dev/null)" ] && opens $D/disk.img "$T0"; ok $? "repli propre sur la phrase de passe : aucune liaison TPM à moitié faite"
unset OB_CRYPT_DEV; S=$($E status); [[ $(js encrypted <<<"$S") == False ]]; ok $? "système non chiffré : état « encrypted: false », aucune erreur"
! grep -qE "$T0|$NEWP|mauvaise|$REC2" $D/crypt.log; ok $? "aucun secret (phrases, clés) dans le journal"
[ "$(stat -c %a $D/state)" = 700 ]; ok $? "dossier d'état en 0700"
pkill -f "[s]wtpm socket"; true
