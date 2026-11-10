#!/bin/bash
exec 9>/tmp/bench/.lock; flock 9   # une seule exécution de test à la fois (ports et système de test partagés)
T=/tmp/target
reset_users() {
  for u in alice bob carol dan; do chroot $T userdel -r $u >/dev/null 2>&1; done
  python3 -c "import json; p='$T/etc/ollamabuntu/users.json'; d=json.load(open(p)); d['users']={k:v for k,v in d['users'].items() if k=='vti'}; json.dump(d,open(p,'w'))"
  printf 'OLLAMA_HOST=127.0.0.1:11434\n' > $T/etc/ollamabuntu/ollama.env
  rm -rf $T/var/lib/ollamabuntu/jobs/* $T/etc/ollamabuntu/open-webui.env $T/etc/ollamabuntu/pools $T/etc/ollamabuntu/pools.json $T/etc/ollamabuntu/placements.json $T/etc/ollamabuntu/ollama-main.env $T/var/lib/ollamabuntu/gpu-inventory.json $T/etc/ollamabuntu/publication.json $T/etc/ollamabuntu/router-tls
}
suite() {  # suite TITRE VARIABLES... -- COMMANDE
  local title=$1; shift; reset_users
  local out; out=$(env "$@" bash /tmp/bench/run.sh 2>&1)
  local okc fail; okc=$(grep -cE "^\[[0-9WS]+\] OK" <<<"$out"); fail=$(grep -E "ÉCHEC|ERREUR|Traceback" <<<"$out" | head -3)
  printf '%-58s %3d OK %s\n' "$title" "$okc" "${fail:+ <<< $fail}"
}
suite "API : comptes, rôles, GPU, paramètres, alimentation" NOSTUB=1 CLIENT="python3 /tmp/apitest2.py"
suite "Interface : connexion, rôles, GPU, comptes, version" NOSTUB=1 CLIENT="node /tmp/uitest/ui.js"
suite "API : mises à jour, modèles, Open WebUI" CLIENT="python3 /tmp/bench/client.py"
suite "Interface : Modèles, Mises à jour, Open WebUI" WEBUI=1 CLIENT="node /tmp/uitest/ui2.js"
suite "Relais Open WebUI : WebSocket" CLIENT="python3 /tmp/bench/ws.py"
suite "Interface : À propos, mise à jour de l'appliance" NOSTUB=1 CLIENT="node /tmp/uitest/ui3.js"
count() { local out; out=$(bash "$2" 2>&1); printf '%-58s %3d OK %s\n' "$1" "$(grep -cE "^\[[0-9]+\] OK" <<<"$out")" "$(grep -E "ÉCHEC|ERREUR|Traceback" <<<"$out" | head -2)"; }
count "Groupes de GPU et épinglage (API, vrai Ollama)" /tmp/bench/run_pl.sh
count "Interface : groupes de GPU et épinglage" /tmp/bench/run_ui4.sh
printf '%-58s %3d OK\n' "Routeur (instances simulées)" "$(timeout 90 python3 /tmp/rt/test.py 2>&1 | grep -cE '^\[[0-9]+\] OK')"
count "Bout en bout : 2 vraies instances Ollama + routeur" /tmp/bench/e2e_pools.sh
count "File des tâches système (APT)" /tmp/bench/run_queue.sh
count "Publication de l'API (console + vrai routeur + vrai Ollama)" /tmp/bench/run_pub.sh
count "Interface : dialogues, file des tâches, publication" /tmp/bench/run_ui5.sh
count "Interface : onglet Sécurité" /tmp/bench/run_ui6.sh
count "Interface : Chat (raisonnement replié)" /tmp/bench/run_ui7.sh
count "Interface : charge GPU" /tmp/bench/run_ui8.sh
count "Modèles personnalisés, préchargement, politique IA" /tmp/bench/run_adv.sh
count "Plusieurs serveurs : 2 vraies consoles (API)" /tmp/bench/run_fleet.sh
count "Interface : onglet Serveurs (2 consoles)" /tmp/bench/run_ui9.sh
count "Répartition de charge : 2 consoles + vrai routeur + vrai Ollama" /tmp/bench/run_lb.sh
count "Interface : répartition et synchronisation (2 consoles)" /tmp/bench/run_ui10.sh
count "Interface : onglets, graphiques, requêtes, journaux en direct" /tmp/bench/run_ui11.sh
printf '%-58s %3d OK\n' "Routeur : politique IA et restrictions par clé" "$(timeout 120 python3 /tmp/rta/test_policy.py 2>&1 | grep -cE '^\[[0-9]+\] OK')"
printf '%-58s %3d OK\n' "Pare-feu réel : sortie Internet d'Ollama" "$(timeout 120 python3 /tmp/fw/egress.py 2>&1 | grep -cE '^\[[0-9]+\] OK')"
printf '%-58s %3d OK\n' "Pare-feu réel (espace réseau isolé)" "$(timeout 200 python3 /tmp/fw/test.py 2>&1 | grep -cE '^\[[0-9]+\] OK')"
printf '%-58s %3d OK\n' "Routeur : contrôle d'accès réseau" "$(timeout 120 python3 /tmp/rta/test.py 2>&1 | grep -cE '^\[[0-9]+\] OK')"
rm -f $T/usr/local/bin/docker $T/usr/local/bin/systemctl
echo "FIN"
count "Taille du contexte : API, routeur, vrai Ollama, interface" /tmp/bench/run_ctx.sh
count "Répartition : choix du serveur et extrait (tests unitaires)" /tmp/bench/run_balance_unit.sh
count "Répartition : 2 consoles, vrai routeur, extrait, conservation" /tmp/bench/run_lb2.sh
count "Interface : répartition, test, extrait de la demande" /tmp/bench/run_ui13.sh
count "Chiffrement du disque : moteur (LUKS réel + TPM logiciel)" /tmp/bench/run_crypt_engine.sh
count "Assistant : disque chiffré (volume LUKS réel)" /tmp/bench/run_wz_crypt.sh
count "Assistant : français (chemin sans chiffrement)" /tmp/bench/run_wz_fr.sh
count "Assistant : anglais (chemin sans chiffrement)" /tmp/bench/run_wz_en.sh
count "Réglage automatique des GPU AMD (9 configurations)" /tmp/bench/run_gpuauto.sh
