#!/usr/bin/env bash
# Avant chaque démarrage d'Ollama : la carte NVIDIA doit être utilisable (pilote chargé, /dev/nvidia-uvm présent),
# sinon Ollama démarre « sans GPU » et reste sur le processeur jusqu'au prochain redémarrage.
# Attend le pilote (45 s au plus), charge les modules manquants, active le mode persistant. Ne bloque JAMAIS Ollama : sortie 0.
SYS=${OB_SYS:-/sys}; DEV=${OB_DEV:-/dev}; WAIT=${OB_GPU_WAIT:-45}; STEP=${OB_GPU_STEP:-2}
say() { echo "gpu-ready : $*"; }
want=0
for d in "$SYS"/bus/pci/devices/*; do
  [[ -r $d/vendor ]] || continue
  [[ $(<"$d/vendor") == 0x10de ]] || continue
  case $(<"$d/class") in 0x03*|0x12*) want=$((want + 1)) ;; esac
done
((want > 0)) || exit 0   # pas de carte NVIDIA : rien à attendre
if ! command -v nvidia-smi >/dev/null 2>&1; then say "$want carte(s) NVIDIA détectée(s) mais pilote non installé"; exit 0; fi
count() { nvidia-smi -L 2>/dev/null | grep -c '^GPU '; }
end=$((SECONDS + WAIT)); n=$(count)
while ((n < want && SECONDS < end)); do
  modprobe nvidia 2>/dev/null || true
  sleep "$STEP"; n=$(count)
done
if ((n < want)); then say "seulement $n carte(s) sur $want utilisable(s) après ${WAIT} s : Ollama démarre quand même"; else say "$n carte(s) NVIDIA prête(s)"; fi
if ((n > 0)) && [[ ! -e $DEV/nvidia-uvm ]]; then
  modprobe nvidia_uvm 2>/dev/null || true
  [[ -e $DEV/nvidia-uvm ]] || { command -v nvidia-modprobe >/dev/null 2>&1 && nvidia-modprobe -u -c=0 2>/dev/null || true; }
  [[ -e $DEV/nvidia-uvm ]] && say "nvidia-uvm chargé" || say "nvidia-uvm toujours absent (CUDA indisponible)"
fi
((n > 0)) && { nvidia-smi -pm 1 >/dev/null 2>&1 || true; }
exit 0
