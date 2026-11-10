# shellcheck shell=bash
# Ollama (embarqué : l'installation fonctionne sans Internet) et modèles préchargés.
# (chargé par build.sh ; ne pas exécuter directement)

fetch_ollama() {
  log "Ollama"
  OLLAMA_FILES=()
  if [[ -n $OLLAMA_ARCHIVE ]]; then
    [[ -f $OLLAMA_ARCHIVE ]] || die "OLLAMA_ARCHIVE introuvable : $OLLAMA_ARCHIVE"
    OLLAMA_FILES+=("$OLLAMA_ARCHIVE")
    OLLAMA_TAG="locale"
    info "archive locale : $OLLAMA_ARCHIVE"
    return
  fi
  local tag=$OLLAMA_VERSION
  if [[ $tag == latest ]]; then latest_ollama_tag; tag=$LATEST_TAG; fi
  [[ $tag == v* ]] || tag="v$tag"
  OLLAMA_TAG=$tag
  info "version : $tag"
  fetch_ollama_asset ollama-linux-amd64; OLLAMA_FILES+=("$ASSET")
  if [[ $INCLUDE_ROCM == 1 ]]; then fetch_ollama_asset ollama-linux-amd64-rocm; OLLAMA_FILES+=("$ASSET"); fi
}

latest_ollama_tag() {   # -> $LATEST_TAG
  local t rc=0 url=https://github.com/ollama/ollama/releases/latest
  t=$(curl -fsSIL --connect-timeout 20 -o /dev/null -w '%{url_effective}' "$url") || rc=$?
  ((rc == 60)) && cert_error "$url"
  ((rc == 0)) || die "impossible de joindre GitHub (code curl $rc) : vérifiez l'accès Internet ou le proxy"
  LATEST_TAG=${t##*/}
}

fetch_ollama_asset() {  # fetch_ollama_asset NOM -> $ASSET (archive téléchargée, SHA-256 vérifiée, en cache)
  local n=$1 tag=$OLLAMA_TAG base dir ext f="" sum=""
  if [[ $tag == locale ]]; then latest_ollama_tag; tag=$LATEST_TAG; fi
  base="https://github.com/ollama/ollama/releases/download/$tag"; dir="$CACHE/ollama-$tag"
  mkdir -p "$dir"
  [[ -s $dir/sha256sum.txt ]] || download "$base/sha256sum.txt" "$dir/sha256sum.txt"
  for ext in tar.zst tgz; do
    sum=$(awk -v f="./$n.$ext" '$2==f || $2==substr(f,3) {print $1}' "$dir/sha256sum.txt")
    [[ -n $sum ]] && { f="$dir/$n.$ext"; break; }
  done
  [[ -n $f ]] || die "$n introuvable dans la release Ollama $tag"
  if ! sha256_ok "$f" "$sum"; then
    download "$base/$(basename "$f")" "$f"
    sha256_ok "$f" "$sum" || die "somme SHA-256 incorrecte pour $(basename "$f")"
  fi
  info "$(basename "$f") : $(du -h "$f" | cut -f1), SHA-256 vérifiée"
  ASSET=$f
}

preload_models() {
  MODELS_TAR=""
  [[ -n $PRELOAD_MODELS ]] || { log "Modèles : aucun modèle embarqué (PRELOAD_MODELS vide)"; return; }
  log "Modèles embarqués : $PRELOAD_MODELS"
  # Un magasin par liste de modèles : il est archivé tel quel (indépendant du format
  # interne d'Ollama, qui a changé en 0.40 : manifests-v2 + liens symboliques).
  local key bin="$W/ollama-bin" store port=11999 pid i m ok=()
  key=$(printf '%s\n' $PRELOAD_MODELS | sort -u | sha256sum | cut -c1-12)
  store="$CACHE/models-$key"
  mkdir -p "$bin" "$store" "$W/ollama-home"
  # Les modèles ne dépendent pas du processeur : on les télécharge avec le binaire
  # Ollama de la machine de build (ARM64 sur Mac Apple Silicon, sans émulation).
  local src
  case $(uname -m) in
    x86_64|amd64)  src=${OLLAMA_FILES[0]} ;;
    aarch64|arm64) info "machine de build ARM64 : binaire Ollama ARM64 utilisé pour télécharger les modèles"
                   fetch_ollama_asset ollama-linux-arm64; src=$ASSET ;;
    *) die "architecture $(uname -m) non prise en charge pour le préchargement ; relancez avec PRELOAD_MODELS=\"\"" ;;
  esac
  rm -f "$bin/bin/ollama"
  case $src in
    *.tar.zst) { zstd -dc "$src" | tar -xf - -C "$bin" --occurrence=1 bin/ollama; } 2>/dev/null || true ;;
    *) { tar -xzf "$src" -C "$bin" --occurrence=1 bin/ollama; } 2>/dev/null || true ;;
  esac
  [[ -x $bin/bin/ollama ]] || die "binaire ollama non extractible de $(basename "$src")"
  local verr
  if ! verr=$(HOME="$W/ollama-home" "$bin/bin/ollama" --version 2>&1); then
    die "le binaire Ollama Linux ne s'exécute pas ici ($(uname -s) $(uname -m)) : $(printf '%s' "$verr" | head -n 2 | tr '\n' ' ' | cut -c1-200)
         Ce script doit tourner dans un vrai Linux : Linux, WSL2, ou conteneur Docker (automatique sous macOS
         et sous Windows depuis Git Bash). Pour construire sans modèle embarqué : PRELOAD_MODELS=\"\""
  fi
  HOME="$W/ollama-home" OLLAMA_MODELS="$store" OLLAMA_HOST="127.0.0.1:$port" "$bin/bin/ollama" serve >"$W/ollama-build.log" 2>&1 &
  pid=$!
  for ((i = 0; i < 30; i++)); do curl -fs "http://127.0.0.1:$port/api/version" >/dev/null 2>&1 && break; sleep 1; done
  for m in $PRELOAD_MODELS; do
    info "téléchargement du modèle $m"
    if HOME="$W/ollama-home" OLLAMA_HOST="127.0.0.1:$port" "$bin/bin/ollama" pull "$m"; then
      ok+=("$m")
    else
      kill "$pid" 2>/dev/null || true
      die "modèle $m : téléchargement impossible (accès à registry.ollama.ai ? nom correct ?).
         Pour construire l'ISO sans modèle embarqué : PRELOAD_MODELS=\"\" $0"
    fi
  done
  kill "$pid" 2>/dev/null || true; wait "$pid" 2>/dev/null || true
  MODELS_TAR="$W/models.tar"
  tar --owner=0 --group=0 --numeric-owner -cf "$MODELS_TAR" -C "$store" .
  PRELOADED="${ok[*]}"
  info "modèles embarqués : $PRELOADED ($(du -h "$MODELS_TAR" | cut -f1))"
}
