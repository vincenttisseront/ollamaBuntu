# Architecture

## Chaîne de construction

`build.sh` charge les bibliothèques de `lib/` puis enchaîne, dans cet ordre :

| Étape | Fonction | Fichier |
|---|---|---|
| Prérequis, certificats d'entreprise | `check_deps`, `use_extra_ca` | `lib/prereqs.sh` |
| ISO Ubuntu Server : téléchargement, vérification, analyse du démarrage | `fetch_ubuntu_iso`, `inspect_iso` | `lib/ubuntu.sh` |
| Ollama (binaire embarqué, somme SHA-256 vérifiée) | `fetch_ollama` | `lib/ollama.sh` |
| Paquets Ubuntu embarqués (signature Canonical via `gpgv`, empreintes des index et des paquets) | `fetch_security_debs` | `lib/packages.sh` |
| Modèles préchargés (facultatif) | `preload_models` | `lib/ollama.sh` |
| Fichiers de l'appliance : copie de `src/rootfs`, informations de construction, version, `rootfs.tar` | `gen_rootfs` | `lib/rootfs.sh` |
| Fin d'installation, mise à jour, fichier autoinstall | `gen_late`, `gen_update`, `gen_autoinstall` | `lib/installer.sh` |
| Menus GRUB (BIOS et UEFI) | `gen_grub` | `lib/grub.sh` |
| ISO finale et vérifications (structure de démarrage conservée, fichiers présents et identiques) | `build_iso`, `verify_iso` | `lib/iso.sh` |

Sous macOS et Windows, `build.sh` (ou `build.ps1`) relance la même chaîne dans un conteneur Ubuntu 24.04 : le dépôt y est
monté en lecture seule (`/opt/ollamabuntu`) et le dossier courant en écriture (`/work`).

## Contenu de l'ISO produite

La structure de démarrage de l'ISO Ubuntu d'origine (El Torito BIOS + UEFI, MBR/GPT hybride) est conservée ; on y ajoute :

- `/autoinstall.yaml` : installation sans question (volume LVM sur le plus grand disque) ; `/autoinstall-update.yaml` : mise à jour ;
- `/boot/grub/grub.cfg` : menu de démarrage (installation, variantes écran de secours / console série, mise à jour si une installation plus ancienne est détectée) ;
- `/ollamabuntu/` : `rootfs.tar` (le contenu de `src/rootfs`), `late.sh`, `update.sh`, `VERSION`, `OLLAMA_VERSION`, `LANG`,
  l'archive Ollama, `models.tar` (modèles embarqués), `debs/` (paquets embarqués) ; avec `DISK_ENCRYPTION=tpm`, `crypt-enabled` et `crypt-temp` ;
- `/OPEN-SOURCE.md` (généré depuis `credits.json`) et `/md5sum.txt` mis à jour.

## Système installé

| Service | Rôle |
|---|---|
| `ollama.service` | Serveur de modèles Ollama, sur un port interne |
| `ollama-pool@.service` | Une instance Ollama par groupe de GPU |
| `ollamabuntu-router.service` | Routeur et contrôle d'accès de l'API : groupes de GPU, clés d'API, politique d'usage de l'IA, répartition de charge entre serveurs, journal des requêtes, taille du contexte (le port 11434 local est l'API des clients) |
| `ollamabuntu-admin.service` | Console d'administration web HTTPS (Python, bibliothèque standard seulement) |
| `ollamabuntu-firewall.service` | Pare-feu `nftables` dans une table dédiée, entrée refusée par défaut |
| `ollamabuntu-firstboot@.service` | Assistant console du premier démarrage |

Les réglages persistants sont dans `/etc/ollamabuntu/` (comptes, publication de l'API, politique d'usage de l'IA, parc de serveurs,
stratégie de répartition, taille du contexte par modèle, réglage du journal des requêtes…), l'état dans `/var/lib/ollamabuntu/`.
Les secrets ne sont conservés que sous forme d'empreinte (clés d'API, jetons de gestion centralisée) et les fichiers sensibles sont en `0600`.

## Mise à jour d'une installation existante

1. GRUB lit `/boot/ollamabuntu-installed.cfg` (version installée) : si elle est plus ancienne que celle de l'ISO, « Mettre à jour » devient
   l'entrée par défaut. Sur un système chiffré, la mise à jour n'est jamais l'entrée par défaut.
2. `update.sh --live` (commande `early-commands` de l'installeur) retrouve le système installé sur les disques, sauvegarde les fichiers de
   l'appliance, applique les nouveaux fichiers, met à jour Ollama et les modèles embarqués si besoin, rejoue `postinstall.sh`, puis redémarre.
3. Depuis le serveur démarré, `ollamabuntu-update` (menu console ou console web) fait la même chose à partir d'un CD, d'une ISO virtuelle ou d'une clé USB.
4. **Depuis Internet** : `admin/updater.py` (console web > Système > Appliance, ou `ollamabuntu-update --online`) lit les releases GitHub, télécharge
   l'archive `ollamabuntu-update-<version>.tar.gz`, vérifie la signature Ed25519 de `SHA256SUMS`, la somme de l'archive et son contenu, télécharge au besoin
   l'archive Ollama officielle (somme contenue dans l'archive signée), puis lance le même `update.sh --target /` avec cette source. L'archive est produite par
   `build.sh --bundle` (`lib/bundle.sh`) et publiée par `.github/workflows/release.yml`. Détails : `docs/MISE-A-JOUR-EN-LIGNE.md`.

## Traduction

Le français est la langue source. Un catalogue unique (`en.json`) est appliqué par deux traducteurs aux résultats identiques :
celui du navigateur (console web) et `i18n.py` (assistant, menu console, bannière, menu de démarrage, messages de construction).
Les sources du catalogue sont dans `tools/i18n/` ; `make i18n-check` vérifie qu'il est à jour.

## Plusieurs serveurs

Une console principale peut superviser d'autres appliances : jetons à portée limitée (supervision et actions de maintenance d'un côté,
requêtes vers les modèles de l'autre), certificats épinglés par empreinte, synchronisation des modèles, de la politique, des clés d'API
et des modèles personnalisés, et répartition de charge avec repli automatique (stratégies « répartir » ou « modèle déjà chargé »).
