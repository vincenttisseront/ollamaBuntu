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
# SearXNG : moteur de recherche web d'Open WebUI, déployé avec lui, publié seulement sur 127.0.0.1
SEARX_NAME=searxng
SEARX_IMAGE=${OB_SEARXNG_IMAGE:-docker.io/searxng/searxng:latest}
SEARX_DIR=${OB_SEARXNG_DIR:-/etc/ollamabuntu/searxng}
SEARX_PORT=8888
SEARX_ENV=${OB_WEBUI_SEARCH_ENV:-/etc/ollamabuntu/open-webui-search.env}
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

# Réglages de SearXNG : format JSON obligatoire pour Open WebUI, pas de limiteur (accès local seulement), clé secrète propre à ce serveur.
searx_prepare() {
  mkdir -p "$SEARX_DIR"
  if [[ ! -s $SEARX_DIR/settings.yml ]]; then
    local key
    key=$(head -c 32 /dev/urandom | od -An -tx1 | tr -d ' \n')
    cat > "$SEARX_DIR/settings.yml" <<YML
# Généré par OllamaBuntu : SearXNG au service d'Open WebUI (accès local uniquement).
use_default_settings: true
general:
  instance_name: "SearXNG"
server:
  secret_key: "$key"
  limiter: false
  image_proxy: false
search:
  formats:
    - html
    - json
YML
  fi
  chown -R 977:977 "$SEARX_DIR" 2>/dev/null || true
}

# Variables transmises à Open WebUI : moteur de recherche = SearXNG. ENABLE_PERSISTENT_CONFIG=false : sans cela Open WebUI garde en base
# le moteur vide lu à son premier démarrage et ignore ces variables.
searx_env() {
  cat > "$SEARX_ENV" <<ENV
# SearXNG (console OllamaBuntu)
ENABLE_PERSISTENT_CONFIG=false
WEB_SEARCH_ENGINE=searxng
SEARXNG_QUERY_URL=http://127.0.0.1:$SEARX_PORT/search
ENV
  chmod 600 "$SEARX_ENV"
}

run_searxng() {
  searx_prepare
  docker rm -f "$SEARX_NAME" >/dev/null 2>&1 || true
  docker run -d --name "$SEARX_NAME" --restart always -p "127.0.0.1:$SEARX_PORT:8080" \
    -v "$SEARX_DIR":/etc/searxng -e "SEARXNG_BASE_URL=http://127.0.0.1:$SEARX_PORT/" \
    --log-driver json-file --log-opt max-size=10m --log-opt max-file=2 "$SEARX_IMAGE" >/dev/null
}

searx_ready() { curl -fsS -o /dev/null "http://127.0.0.1:$SEARX_PORT/healthz" 2>/dev/null || curl -fsS -o /dev/null "http://127.0.0.1:$SEARX_PORT/" 2>/dev/null; }

wait_searx() {
  local i
  say "Démarrage de SearXNG..."
  for ((i = 0; i < 40; i++)); do
    if searx_ready; then say "SearXNG répond."; return 0; fi
    sleep 3
  done
  say "ERREUR : SearXNG ne répond pas. Dernières lignes de son journal :"
  docker logs --tail 40 "$SEARX_NAME" 2>&1 || true
  return 1
}

# Garantit que SearXNG tourne (démarre le conteneur arrêté, le crée s'il manque, le recrée s'il ne répond pas).
ensure_searx() {
  local st
  st=$(docker inspect -f '{{.State.Status}}' "$SEARX_NAME" 2>/dev/null || echo absent)
  case $st in
    running) searx_ready && return 0; say "SearXNG ne répond pas : recréation"; run_searxng; wait_searx ;;
    absent) run_searxng; wait_searx ;;
    *) docker start "$SEARX_NAME" >/dev/null 2>&1 || run_searxng; wait_searx ;;
  esac
}

run_container() {
  ensure_searx || say "AVERTISSEMENT : SearXNG indisponible, la recherche sur Internet d'Open WebUI ne fonctionnera pas (la console le relance automatiquement)."
  searx_env
  docker rm -f "$NAME" >/dev/null 2>&1 || true
  local pol=()
  [[ -f /etc/ollamabuntu/open-webui-policy.env ]] && pol=(--env-file /etc/ollamabuntu/open-webui-policy.env)
  # Plafond de mémoire (réglage « Performance » de la console) : /etc/ollamabuntu/open-webui.limits contient MEM=2g
  local lim=() mem=""
  [[ -f /etc/ollamabuntu/open-webui.limits ]] && mem=$(sed -n 's/^MEM=\([0-9]\{1,4\}[mg]\)$/\1/p' /etc/ollamabuntu/open-webui.limits | head -n1)
  [[ -n $mem ]] && lim=(--memory "$mem" --memory-swap "$mem")
  local url=()
  [[ -f /etc/ollamabuntu/open-webui-url.env ]] && url=(--env-file /etc/ollamabuntu/open-webui-url.env)
  local srx=(--env-file "$SEARX_ENV")
  local sso=()
  [[ -f /etc/ollamabuntu/open-webui-sso.env ]] && sso=(--env-file /etc/ollamabuntu/open-webui-sso.env)
  docker run -d --name "$NAME" --restart always --network host \
    -v open-webui:/app/backend/data --env-file "$ENVF" "${pol[@]}" "${url[@]}" "${srx[@]}" "${sso[@]}" "${lim[@]}" "$IMAGE" >/dev/null
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
    say "Téléchargement de l'image $SEARX_IMAGE"
    docker pull "$SEARX_IMAGE"
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
    say "Téléchargement de la dernière image $SEARX_IMAGE"
    docker pull "$SEARX_IMAGE"
    run_searxng
    wait_searx
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
  apply-url)
    need_docker
    say "Application de l'adresse publique (recréation du conteneur, données conservées)"
    run_container
    wait_ready
    say "Adresse publique appliquée."
    ;;
  apply-sso)
    need_docker
    say "Application de la connexion unique (recréation du conteneur, données conservées)"
    run_container
    wait_ready
    say "Connexion unique appliquée."
    ;;
  ensure-searx)
    need_docker
    ensure_searx
    ;;
  start)   docker start "$NAME" >/dev/null ;;
  stop)    docker stop "$NAME" >/dev/null ;;
  restart) docker restart "$NAME" >/dev/null ;;
  remove)
    docker rm -f "$NAME" "$SEARX_NAME" >/dev/null 2>&1 || true
    say "Conteneurs supprimés. Les conversations et comptes restent dans le volume « open-webui »."
    ;;
  purge)
    docker rm -f "$NAME" "$SEARX_NAME" >/dev/null 2>&1 || true
    docker volume rm open-webui >/dev/null 2>&1 || true
    rm -f "$ENVF" /etc/ollamabuntu/open-webui-url.env /etc/ollamabuntu/open-webui-sso.env /etc/ollamabuntu/open-webui-sso.json "$SEARX_ENV"
    rm -rf "$SEARX_DIR"
    say "Open WebUI et toutes ses données ont été supprimés."
    ;;
  *) echo "usage : $0 install|update|apply|apply-url|apply-sso|ensure-searx|start|stop|restart|remove|purge" >&2; exit 2 ;;
esac
