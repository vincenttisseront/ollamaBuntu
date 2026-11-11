#!/usr/bin/env bash
# gpu-ready.sh : attente du pilote NVIDIA avant Ollama (arborescence /sys et /dev factice, commandes simulées).
cd "$(dirname "$0")/../.." || exit 1
S=$PWD/src/rootfs/usr/local/lib/ollamabuntu/gpu-ready.sh
n=0; ok() { n=$((n+1)); if [[ $1 == 0 ]]; then echo "[$n] OK   - $2"; else echo "[$n] ÉCHEC - $2"; exit 1; fi; }
t=$(mktemp -d); trap 'rm -rf "$t"' EXIT
mkdir -p "$t/bin" "$t/dev" "$t/sys/bus/pci/devices/0000:01:00.0"
printf '0x10de' > "$t/sys/bus/pci/devices/0000:01:00.0/vendor"; printf '0x030000' > "$t/sys/bus/pci/devices/0000:01:00.0/class"
log="$t/calls"
# nvidia-smi : « -L » ne liste la carte qu'après le chargement du module (fichier témoin créé par modprobe nvidia)
cat > "$t/bin/nvidia-smi" <<EOS
#!/bin/sh
echo "smi \$*" >> "$log"
[ "\$1" = "-L" ] && [ -e "$t/loaded" ] && echo "GPU 0: Quadro RTX 4000 (UUID: x)"
exit 0
EOS
cat > "$t/bin/modprobe" <<EOS
#!/bin/sh
echo "modprobe \$*" >> "$log"
[ "\$1" = nvidia ] && touch "$t/loaded"
[ "\$1" = nvidia_uvm ] && touch "$t/dev/nvidia-uvm"
exit 0
EOS
chmod +x "$t/bin/"*
run() { PATH="$t/bin:/usr/bin:/bin" OB_SYS="$t/sys" OB_DEV="$t/dev" OB_GPU_WAIT=${W:-6} OB_GPU_STEP=1 bash "$S"; }
out=$(run); rc=$?
[[ $rc == 0 ]]; ok $? "sortie 0 (ne bloque jamais Ollama)"
grep -q '^modprobe nvidia$' "$log"; ok $? "module nvidia chargé quand la carte n'est pas encore utilisable"
grep -q '^modprobe nvidia_uvm$' "$log"; ok $? "nvidia-uvm chargé quand /dev/nvidia-uvm manque"
grep -q '^smi -pm 1$' "$log"; ok $? "mode persistant activé"
[[ $out == *"1 carte(s) NVIDIA prête(s)"* ]]; ok $? "message : carte prête"
: > "$log"; run >/dev/null
! grep -q '^modprobe' "$log"; ok $? "déjà prête : aucun chargement de module"
rm -f "$t/loaded" "$t/dev/nvidia-uvm"; : > "$log"; rm "$t/bin/modprobe"; printf '#!/bin/sh\nexit 0\n' > "$t/bin/modprobe"; chmod +x "$t/bin/modprobe"
start=$SECONDS; W=3 run > "$t/o" 2>&1; rc=$?
[[ $rc == 0 && $((SECONDS - start)) -le 6 ]]; ok $? "pilote introuvable : attente bornée (3 s), puis Ollama démarre quand même"
grep -q "seulement 0 carte" "$t/o"; ok $? "message : carte inutilisable après l'attente"
rm "$t/bin/nvidia-smi"; out=$(run); [[ $? == 0 && $out == *"pilote non installé"* ]]; ok $? "pilote NVIDIA non installé : signalé, sans attente"
rm -rf "$t/sys/bus/pci/devices/0000:01:00.0"; mkdir -p "$t/sys/bus/pci/devices/0000:02:00.0"; printf '0x1002' > "$t/sys/bus/pci/devices/0000:02:00.0/vendor"; printf '0x030000' > "$t/sys/bus/pci/devices/0000:02:00.0/class"
start=$SECONDS; out=$(run); [[ $? == 0 && -z $out && $((SECONDS - start)) -le 1 ]]; ok $? "serveur sans carte NVIDIA : aucun effet"
