# shellcheck shell=bash
# Archive de mise à jour en ligne (publiée dans une release GitHub) : les mêmes fichiers d'appliance que l'ISO,
# sans Ubuntu, sans modèle et sans binaire Ollama. L'appliance télécharge Ollama elle-même ; l'adresse et la somme
# SHA-256 de l'archive officielle sont dans l'archive de mise à jour, donc couvertes par la signature.
# (chargé par build.sh ; ne pas exécuter directement)

BUNDLE_PUBKEY="$OB_ROOT/src/rootfs/usr/local/lib/ollamabuntu/update-pubkey.pem"

build_bundle() {
  log "Archive de mise à jour en ligne $OB_VERSION"
  [[ $OB_VERSION =~ ^[0-9]{4}\.[0-9]{2}\.[0-9]{2}-[0-9]{4}$ ]] || die "OB_VERSION doit avoir la forme AAAA.MM.JJ-HHMM (reçu : $OB_VERSION)"
  [[ $OB_LANG == fr || $OB_LANG == en ]] || die "OB_LANG doit valoir fr ou en (reçu : $OB_LANG)"
  mkdir -p "$CACHE" "$W"
  use_extra_ca
  local cmd missing=()
  for cmd in curl python3 tar gzip sha256sum awk sed find; do need "$cmd" || missing+=("$cmd"); done
  ((${#missing[@]} == 0)) || die "outils manquants : ${missing[*]}"

  # Ollama : version, adresses et sommes de l'archive officielle (rien n'est téléchargé ici)
  local tag=$OLLAMA_VERSION base dir name sum ext
  if [[ $tag == latest ]]; then latest_ollama_tag; tag=$LATEST_TAG; fi
  [[ $tag == v* ]] || tag="v$tag"
  OLLAMA_TAG=$tag
  base="https://github.com/ollama/ollama/releases/download/$tag"; dir="$CACHE/ollama-$tag"
  mkdir -p "$dir"
  [[ -s $dir/sha256sum.txt ]] || download "$base/sha256sum.txt" "$dir/sha256sum.txt"
  info "Ollama : $tag"

  UBUNTU_NAME=""; PRELOADED=""; INCLUDE_ROCM=0   # informations d'origine conservées par update.sh (installation d'origine)
  rm -rf "$W/iso" "$W/bundle"; mkdir -p "$W/iso/ollamabuntu" "$W/bundle"
  gen_rootfs
  gen_late
  gen_update
  local f
  for f in VERSION OLLAMA_VERSION LANG rootfs.tar update.sh; do cp "$W/iso/ollamabuntu/$f" "$W/bundle/$f"; done
  printf '%s\n' 1 > "$W/bundle/ONLINE"
  for name in ollama-linux-amd64 ollama-linux-amd64-rocm; do
    sum="" ext=""
    for ext in tar.zst tgz; do
      sum=$(awk -v f="./$name.$ext" '$2==f || $2==substr(f,3) {print $1}' "$dir/sha256sum.txt")
      [[ -n $sum ]] && break
    done
    if [[ -z $sum ]]; then
      [[ $name == ollama-linux-amd64 ]] && die "$name introuvable dans la release Ollama $tag"
      continue
    fi
    [[ $sum =~ ^[0-9a-f]{64}$ ]] || die "somme SHA-256 illisible pour $name"
    if [[ $name == ollama-linux-amd64 ]]; then
      printf '%s\n' "$base/$name.$ext" > "$W/bundle/OLLAMA_URL"; printf '%s\n' "$sum" > "$W/bundle/OLLAMA_SHA256"
    else
      printf '%s\n' "$base/$name.$ext" > "$W/bundle/OLLAMA_ROCM_URL"; printf '%s\n' "$sum" > "$W/bundle/OLLAMA_ROCM_SHA256"
    fi
  done

  local out=${OUTPUT:-$PWD/ollamabuntu-update-$OB_VERSION.tar.gz} files
  files=$(cd "$W/bundle" && ls | sort | tr '\n' ' ')
  # shellcheck disable=SC2086
  (cd "$W/bundle" && tar --owner=0 --group=0 --numeric-owner --mtime='UTC 2026-01-01' -cf - $files) | gzip -n -9 > "$out"
  info "$(basename "$out") : $(du -h "$out" | cut -f1) ($files)"
  sign_bundle "$out"
}

# Somme + signature Ed25519 (clé privée : OB_SIGNING_KEY, fichier PEM). Sans clé : archive non signée, donc refusée par les appliances.
sign_bundle() {
  local out=$1 d; d=$(dirname "$out")
  ( cd "$d" && sha256sum "$(basename "$out")" > SHA256SUMS )
  if [[ -z ${OB_SIGNING_KEY:-} ]]; then
    warn "OB_SIGNING_KEY absent : archive non signée (les appliances la refuseront)"
    return 0
  fi
  [[ -f $OB_SIGNING_KEY ]] || die "OB_SIGNING_KEY introuvable : $OB_SIGNING_KEY"
  need openssl || die "openssl est nécessaire pour signer l'archive"
  openssl pkeyutl -sign -inkey "$OB_SIGNING_KEY" -rawin -in "$d/SHA256SUMS" -out "$d/SHA256SUMS.sig" || die "signature impossible"
  # contrôle immédiat avec la clé publique livrée dans l'appliance : une signature d'une autre clé serait refusée partout
  openssl pkeyutl -verify -pubin -inkey "$BUNDLE_PUBKEY" -rawin -in "$d/SHA256SUMS" -sigfile "$d/SHA256SUMS.sig" >/dev/null \
    || die "la signature ne correspond pas à la clé publique de l'appliance (update-pubkey.pem) : mauvaise clé privée ?"
  info "signature vérifiée avec la clé publique de l'appliance"
}
