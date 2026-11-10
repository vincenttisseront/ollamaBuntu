Q = "\u201c{1}\u201d"
E = {
"GPU intégré ou à faible mémoire vidéo": "integrated GPU or low video memory", "famille différente des autres cartes": "different family from the other cards",
"cible non prise en charge par ROCm": "target not supported by ROCm", "Vulkan est installé.": "Vulkan is installed.",
"Le compte ollama n'a pas accès au périphérique ROCm (/dev/kfd, groupe render) : appliquez la mise à jour de l'appliance, puis redémarrez le serveur.":
  "The ollama account cannot access the ROCm device (/dev/kfd, render group): apply the appliance update, then restart the server.",
">>> Les GPU AMD sont réglés automatiquement à chaque démarrage d'Ollama (détail par carte dans l'onglet GPU).":
  ">>> AMD GPUs are tuned automatically each time Ollama starts (details per card in the GPU tab).",
}
P = [
(r"Prise en charge native par le module ROCm \((\S+)\) : aucun contournement nécessaire\.", "Natively supported by the ROCm module ({1}): no workaround needed."),
(r"Cible (\S+) absente du module ROCm : contournement appliqué automatiquement \(HSA_OVERRIDE_GFX_VERSION=(\S+)\)\.", "Target {1} missing from the ROCm module: workaround applied automatically (HSA_OVERRIDE_GFX_VERSION={2})."),
(r"Écartée automatiquement de ROCm \((\S+)\) : (.+), pour ne pas gêner les autres cartes\.", "Automatically excluded from ROCm ({1}): {2}, so as not to disturb the other cards."),
(r"Cible (\S+) non prise en charge par le module ROCm : utilisez Vulkan\.", "Target {1} not supported by the ROCm module: use Vulkan."),
(r"Dernier message d'Ollama sur ROCm : « (.+) »\.", "Last Ollama message about ROCm: \u201c{1}\u201d."),
]
