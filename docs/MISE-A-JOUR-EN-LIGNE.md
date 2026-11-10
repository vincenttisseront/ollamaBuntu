# Mise à jour en ligne (sans ISO)

Une appliance déjà installée peut se mettre à jour **depuis Internet**, à partir des versions publiées dans les *releases*
GitHub du dépôt, sans reconstruire ni réinsérer d'ISO. Comptes, réseau, certificats, réglages, modèles et données sont conservés
(même procédure que la mise à jour par ISO : `update.sh`).

## Côté administrateur

Console web > **Système > Appliance** > carte « Mise à jour depuis Internet » :

1. **Rechercher une mise à jour** interroge GitHub. Rien n'est contacté avant ce clic, sauf si la case « Rechercher automatiquement
   une nouvelle version chaque jour » est cochée (décochée par défaut).
2. Si une version plus récente existe, la carte affiche ses notes et le bouton **Mettre à jour vers vAAAA.MM.JJ-HHMM**.
   La vue d'ensemble de la console signale aussi qu'une version est disponible (dès la dernière vérification connue).
3. La mise à jour est une tâche de la file système : téléchargement, vérification, application, puis redémarrage des services.
   La console suit l'opération et se recharge sur la nouvelle version.

Réglages (repliés dans la carte) : dépôt GitHub (`propriétaire/dépôt`, par défaut celui du projet), versions stables seulement ou
stables + préversions, vérification automatique, jeton d'accès en lecture pour un dépôt **privé**.

En ligne de commande (SSH ou console) :

```sh
sudo ollamabuntu-update --check      # une version plus récente est-elle publiée ?
sudo ollamabuntu-update --online     # télécharger, vérifier, appliquer (demande confirmation ; --yes pour l'éviter)
```

## Ce qui est vérifié avant d'appliquer

| Contrôle | Détail |
|---|---|
| Signature | `SHA256SUMS` est signé en Ed25519 ; la clé publique est livrée avec l'appliance (`/usr/local/lib/ollamabuntu/update-pubkey.pem`). Signature absente, invalide ou clé absente : refus. |
| Somme SHA-256 | de l'archive, comparée à celle de `SHA256SUMS` signé. |
| Contenu | l'archive ne peut contenir que les fichiers attendus (à plat : ni sous-dossier, ni lien, ni `..`) ; le fichier `VERSION` doit égaler la version de la release. |
| Ollama | l'archive officielle (github.com/ollama/ollama) est téléchargée si la version change ; son adresse et sa somme SHA-256 sont dans l'archive signée, donc couvertes par la signature. |
| Version | pas de retour en arrière sans `--force` en ligne de commande. |
| Réseau | HTTPS vers `api.github.com`, `github.com` et `*.githubusercontent.com` seulement, y compris après redirection ; le jeton n'est envoyé qu'à `api.github.com`. |
| Espace disque | vérifié avant chaque téléchargement ; avant remplacement, une sauvegarde des fichiers de l'appliance est faite (`/var/backups/ollamabuntu`). |

Les modèles ne sont pas inclus dans une mise à jour en ligne (ceux déjà installés sont conservés).

## Côté éditeur : publier une version

Une fois :

1. Générer la paire de clés de signature (déjà fait pour ce dépôt : la clé publique est dans `src/rootfs/usr/local/lib/ollamabuntu/update-pubkey.pem`) :
   ```sh
   openssl genpkey -algorithm ed25519 -out update-signing-key.pem
   openssl pkey -in update-signing-key.pem -pubout -out src/rootfs/usr/local/lib/ollamabuntu/update-pubkey.pem
   ```
2. Enregistrer la **clé privée** dans le secret GitHub `OB_UPDATE_SIGNING_KEY` (Settings > Secrets and variables > Actions, ou
   `gh secret set OB_UPDATE_SIGNING_KEY < update-signing-key.pem`), puis la conserver ailleurs (gestionnaire de mots de passe). **Ne jamais la committer.**
   Perdre la clé impose de livrer une nouvelle clé publique par ISO ou par une mise à jour signée de l'ancienne clé ; la divulguer permet à
   quiconque d'installer du code sur toutes les appliances : la révoquer exige alors une nouvelle ISO.

À chaque version :

```sh
git push origin main
tools/release/new-release.sh "Ce qui change dans cette version"            # version stable
tools/release/new-release.sh --preview "Version à tester"                  # préversion
```

Le script crée le tag `vAAAA.MM.JJ-HHMM` (la date et l'heure locales deviennent le numéro de version, comme pour `build.sh`) ; le workflow `.github/workflows/release.yml` lance
les tests, construit l'archive (`./build.sh --bundle`), la signe et crée la release (archive, `SHA256SUMS`, `SHA256SUMS.sig`).
Les notes de la release sont le message du tag. Construire l'archive à la main : `OB_VERSION=… OB_SIGNING_KEY=clé.pem ./build.sh --bundle`.

**Sans GitHub Actions** (minutes épuisées, facturation suspendue, ou préférence) : `tools/release/publish-local.sh "notes"` construit, signe et publie
depuis votre poste avec la CLI `gh` ; la clé privée reste alors dans `.secrets/update-signing-key.pem` (ignoré par git). Si le tag est ensuite vu par le
workflow, celui-ci constate que la release existe et ne fait rien.

## Dépôt privé

Les appliances interrogent l'API GitHub sans authentification : cela suffit pour un dépôt **public**. Pour un dépôt privé, créer un
jeton d'accès à granularité fine (*fine-grained personal access token*) limité à ce seul dépôt, avec la seule permission
« Contents : lecture », et le saisir dans les réglages de la carte. Il est conservé dans `/etc/ollamabuntu/update-token` (0600, root).
Le choix public/privé du dépôt vous appartient ; en l'absence de licence, un dépôt public n'accorde aucun droit d'usage (voir README).

## Limites

- Non vérifié sur une vraie appliance installée à ce jour : l'application finale (`update.sh --target /`) est celle de la mise à jour par ISO, déjà éprouvée par le banc ;
  les tests portables couvrent la détection, le téléchargement, la signature et les falsifications (`tests/unit/online_update_test.py`, `online_update_ui_test.js`).
- Le téléchargement d'Ollama (plusieurs Go) dépend de la bande passante du serveur ; il n'est pas repris en cas d'interruption.
- Un proxy d'entreprise qui inspecte le HTTPS doit présenter un certificat reconnu par le serveur (magasin de certificats d'Ubuntu).
- Le numéro de version sert d'ordre (`AAAA.MM.JJ-HHMM`, heure locale de la machine qui publie) : deux tags ne peuvent pas partager la même minute, et publier depuis un fuseau
  horaire en retard sur celui des ISO précédentes produirait un numéro « plus ancien » (les appliances ne reculent pas).
