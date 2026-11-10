#!/usr/bin/env bash
# Publie une version : crée le tag vAAAA.MM.JJ-HHMM (daté de maintenant) et le pousse ; GitHub Actions construit,
# signe et publie l'archive de mise à jour en ligne (.github/workflows/release.yml).
#   tools/release/new-release.sh "Notes de version (une ou plusieurs lignes)"
#   tools/release/new-release.sh --preview "Notes"     préversion (canal « préversions » des appliances)
set -Eeuo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")/../.."
preview=""
if [[ ${1:-} == --preview ]]; then preview=" [preview]"; shift; fi
notes=${1:-}
[[ -n $notes ]] || { echo "usage : $0 [--preview] \"notes de version\"" >&2; exit 2; }
[[ -z $(git status --porcelain) ]] || { echo "des modifications ne sont pas validées : commit d'abord" >&2; exit 1; }
git fetch --quiet origin
[[ $(git rev-parse HEAD) == "$(git rev-parse '@{upstream}')" ]] || { echo "la branche locale diffère de origin : poussez ou récupérez d'abord" >&2; exit 1; }
version=$(date +%Y.%m.%d-%H%M)   # heure locale, comme OB_VERSION de build.sh : les numéros restent comparables entre ISO et mises à jour en ligne
tag="v$version"
last=$(git tag -l 'v[0-9][0-9][0-9][0-9].*' | sort | tail -n1)
[[ -z $last || $tag > $last ]] || { echo "le tag $tag n'est pas postérieur à $last" >&2; exit 1; }
python3 tools/i18n/build_catalog.py --check
git tag -a "$tag" -m "$notes$preview"
git push origin "$tag"
echo "Tag $tag poussé : suivez la publication dans l'onglet Actions du dépôt."
