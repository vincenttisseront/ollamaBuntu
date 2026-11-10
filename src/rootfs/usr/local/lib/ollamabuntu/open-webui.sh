#!/bin/bash
# =============================================================================
#  OllamaBuntu - déploiement et gestion d'Open WebUI (conteneur Docker)
#    install | update | start | stop | restart | remove | purge
#  Open WebUI écoute sur 127.0.0.1:3000 ; la console OllamaBuntu le publie en
#  HTTPS sur le port 8443 (même certificat que l'administration web).
# =============================================================================
set -Eeuo pipefail
export PATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin
IMAGE=${OB_WEBUI_IMAGE:-ghcr.io/open-webui/open-webui:main}
NAME=open-webui
ENVF=${OB_WEBUI_ENV:-/etc/ollamabuntu/open-webui.env}
PORT=3000
MIN_FREE_KB=${OB_WEBUI_MIN_FREE_KB:-8388608}
say() { echo ">>> $*"; }
trap 'say "ERREUR à la ligne $LINENO : $BASH_COMMAND"' ERR

need_docker() {
  if ! command -v docker >/dev/null 2>&1; then
    say "Installation de Docker (paquet docker.io d'Ubuntu)"
    export DEBIAN_FRONTEND=noninteractive NEEDRESTART_MODE=a
    apt-get update
    apt-get install -y docker.io
  fi
  systemctl enable --now docker >/dev/null 2>&1 || systemctl start docker
}

check_space() {
  local free
  # (|| true : avant le premier conteneur, /var/lib/docker peut ne pas exister)
  free=$(df -Pk /var/lib/docker 2>/dev/null | awk 'NR==2 {print $4}' || true)
  [[ -n $free ]] || free=$(df -Pk /var/lib | awk 'NR==2 {print $4}')
  if ((free < MIN_FREE_KB)); then
    say "ERREUR : moins de 8 Go libres pour Docker ($((free / 1024)) Mo)."
    exit 1
  fi
}

run_container() {
  docker rm -f "$NAME" >/dev/null 2>&1 || true
  local pol=()
  [[ -f /etc/ollamabuntu/open-webui-policy.env ]] && pol=(--env-file /etc/ollamabuntu/open-webui-policy.env)
  docker run -d --name "$NAME" --restart always --network host \
    -v open-webui:/app/backend/data --env-file "$ENVF" "${pol[@]}" "$IMAGE" >/dev/null
}

wait_ready() {
  local i
  say "Démarrage d'Open WebUI (jusqu'à 5 minutes au premier lancement)..."
  for ((i = 0; i < 100; i++)); do
    if curl -fsS "http://127.0.0.1:$PORT/health" >/dev/null 2>&1; then say "Open WebUI répond."; return 0; fi
    sleep 3
  done
  say "ERREUR : Open WebUI ne répond pas. Dernières lignes de son journal :"
  docker logs --tail 60 "$NAME" 2>&1 || true
  return 1
}

case "${1:-}" in
  install)
    [[ -f $ENVF ]] || { say "ERREUR : configuration absente ($ENVF)."; exit 1; }
    need_docker
    check_space
    say "Téléchargement de l'image $IMAGE (plusieurs Go, patience)"
    docker pull "$IMAGE"
    run_container
    wait_ready
    if grep -q '^WEBUI_ADMIN_PASSWORD=' "$ENVF"; then
      # Le compte administrateur existe désormais : le mot de passe initial n'a plus à
      # rester dans la configuration ni dans celle du conteneur.
      sed -i '/^WEBUI_ADMIN_PASSWORD=/d' "$ENVF"
      say "Compte administrateur créé ; mot de passe initial retiré de la configuration."
      run_container
      wait_ready
    fi
    say "Open WebUI est prêt : https://<adresse-du-serveur>:8443/"
    ;;
  update)
    need_docker
    say "Téléchargement de la dernière image $IMAGE"
    docker pull "$IMAGE"
    run_container
    wait_ready
    docker image prune -f >/dev/null 2>&1 || true
    say "Mise à jour terminée."
    ;;
  apply)
    need_docker
    say "Application de la politique d'usage de l'IA (recréation du conteneur, données conservées)"
    run_container
    wait_ready
    say "Politique appliquée."
    ;;
  start)   docker start "$NAME" >/dev/null ;;
  stop)    docker stop "$NAME" >/dev/null ;;
  restart) docker restart "$NAME" >/dev/null ;;
  remove)
    docker rm -f "$NAME" >/dev/null 2>&1 || true
    say "Conteneur supprimé. Les conversations et comptes restent dans le volume « open-webui »."
    ;;
  purge)
    docker rm -f "$NAME" >/dev/null 2>&1 || true
    docker volume rm open-webui >/dev/null 2>&1 || true
    rm -f "$ENVF"
    say "Open WebUI et toutes ses données ont été supprimés."
    ;;
  *) echo "usage : $0 install|update|start|stop|restart|remove|purge" >&2; exit 2 ;;
esac
