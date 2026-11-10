#!/usr/bin/env bash
# Publie une version depuis le poste du mainteneur, SANS GitHub Actions : construit et signe l'archive de mise à jour
# en ligne, puis crée la release (archive, SHA256SUMS, SHA256SUMS.sig) avec la CLI gh.
#   tools/release/publish-local.sh [--preview] "Notes de version"
# Clé privée de signature : $OB_SIGNING_KEY, sinon .secrets/update-signing-key.pem (jamais versionnée).
# Prérequis : bash, curl, python3, openssl, gh (connecté : gh auth login). Sous Windows : WSL2 ou Git Bash avec ces outils.
set -Eeuo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")/../.."
root=$PWD
die() { echo "[ERREUR] $*" >&2; exit 1; }
flags=()
if [[ ${1:-} == --preview ]]; then flags+=(--prerelease); shift; fi
notes=${1:-}
[[ -n $notes ]] || die "usage : $0 [--preview] \"notes de version\""
key=${OB_SIGNING_KEY:-$root/.secrets/update-signing-key.pem}
[[ -f $key ]] || die "clé de signature introuvable : $key (variable OB_SIGNING_KEY)"
for c in gh git openssl python3 curl; do command -v "$c" >/dev/null || die "outil manquant : $c"; done
[[ -z $(git status --porcelain) ]] || die "des modifications ne sont pas validées : commit et push d'abord"
git fetch --quiet origin
[[ $(git rev-parse HEAD) == "$(git rev-parse '@{upstream}')" ]] || die "la branche locale diffère de origin : poussez ou récupérez d'abord"
version=$(date +%Y.%m.%d-%H%M)   # heure locale, comme OB_VERSION de build.sh
tag="v$version"
last=$(git ls-remote --tags --refs origin 'v[0-9][0-9][0-9][0-9].*' | sed 's|.*refs/tags/||' | sort | tail -n1)
[[ -z $last || $tag > $last ]] || die "le tag $tag n'est pas postérieur à $last"
python3 tools/i18n/build_catalog.py --check
out=$(mktemp -d)
trap 'rm -rf "$out"' EXIT
(cd "$out" && OB_VERSION=$version OB_SIGNING_KEY=$key bash "$root/build.sh" --bundle)
ls -l "$out"/ollamabuntu-update-*.tar.gz "$out/SHA256SUMS" "$out/SHA256SUMS.sig"
[[ -s $out/SHA256SUMS.sig ]] || die "archive non signée : publication annulée"
gh release create "$tag" "${flags[@]}" --target "$(git rev-parse HEAD)" --title "OllamaBuntu $version" --notes "$notes" \
  "$out"/ollamabuntu-update-*.tar.gz "$out/SHA256SUMS" "$out/SHA256SUMS.sig"
echo "Version $version publiée : les appliances la détectent depuis Système > Appliance."
