#!/usr/bin/env bash
# Construction dans un conteneur (macOS/Windows) : la clé de signature est montée en lecture seule et transmise (docker simulé).
cd "$(dirname "$0")/../.." || exit 1
n=0; ok() { n=$((n+1)); if [[ $1 == 0 ]]; then echo "[$n] OK   - $2"; else echo "[$n] ÉCHEC - $2"; exit 1; fi; }
tmp=$(mktemp -d); trap 'rm -rf "$tmp"' EXIT
mkdir "$tmp/bin"; printf '#!/bin/sh\n[ "$1" = info ] && exit 0\nprintf "%%s\\n" "$@" > "%s/args"\n' "$tmp" > "$tmp/bin/docker"; chmod +x "$tmp/bin/docker"
printf 'PRIVATE' > "$tmp/key.pem"
run() {   # $1 : type d'hôte simulé ; le reste : environnement
  ( export PATH="$tmp/bin:$PATH" OB_ROOT=$PWD OLLAMA_ARCHIVE="" OUTPUT=""; cd "$tmp" || exit 1
    # shellcheck disable=SC1091
    source "$OLDPWD/lib/common.sh"; source "$OLDPWD/lib/host.sh"
    SIMKIND=$1; host_kind() { echo "$SIMKIND"; }; host_path() { printf '%s' "$1"; }
    shift; eval "$*"; run_in_docker --bundle ) >/dev/null 2>&1
}
rm -f "$tmp/args"; run macos "export OB_SIGNING_KEY=$tmp/key.pem"
grep -q "^$tmp/key.pem:/run/ob-signing-key.pem:ro$" "$tmp/args"; ok $? "macOS/Linux : clé montée en lecture seule"
grep -q '^OB_SIGNING_KEY=/run/ob-signing-key.pem$' "$tmp/args"; ok $? "variable pointant vers la clé dans le conteneur"
grep -q "PRIVATE" "$tmp/args"; [[ $? != 0 ]]; ok $? "le contenu de la clé n'apparaît jamais dans les arguments"
rm -f "$tmp/args"; run windows "export OB_SIGNING_KEY=$tmp/key.pem"
grep -q "^type=bind,source=$tmp/key.pem,target=/run/ob-signing-key.pem,readonly$" "$tmp/args"; ok $? "Windows : montage --mount en lecture seule"
rm -f "$tmp/args"; run macos "unset OB_SIGNING_KEY"
! grep -q 'ob-signing-key' "$tmp/args"; ok $? "sans clé : aucun montage"
rm -f "$tmp/args"; run macos "export OB_SIGNING_KEY=$tmp/absente.pem"
! grep -q 'ob-signing-key' "$tmp/args"; ok $? "clé introuvable : rien de monté (le script de construction signale l'erreur)"
