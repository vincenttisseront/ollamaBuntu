# Chiffrement du disque (`DISK_ENCRYPTION=tpm`)

Désactivé par défaut. `DISK_ENCRYPTION=tpm ./build.sh` (ou `-DiskEncryption tpm` avec `build.ps1`) produit une ISO qui installe le système
sur un **volume LVM chiffré en LUKS2** ; `/boot` reste en clair.

> **État de validation.** Les mécanismes de clés sont testés sur de vrais en-têtes LUKS2 avec un TPM logiciel (`tests/unit/crypt_engine_test.sh`),
> et l'assistant sur un vrai volume. **L'installation chiffrée complète n'a pas été exécutée** (pas d'installation Ubuntu possible dans
> l'environnement de développement) : à valider sur une VM avec TPM virtuel avant tout usage réel.

## Principe

1. **Installation** : l'installeur chiffre le volume avec une **phrase provisoire** aléatoire (24 caractères), générée à chaque construction et
   écrite dans l'ISO (`crypt-temp`). Quiconque détient l'ISO la connaît : elle ne doit vivre que le temps de l'installation.
2. **Fin d'installation** (`ollamabuntu-crypt setup`, appelé par `late.sh`) :
   - une **clé de récupération** de 256 bits est ajoutée (9 groupes de caractères A-Z 2-7) ;
   - si un TPM2 est utilisable, le déverrouillage y est **lié** (`clevis`, PCR 7) puis la phrase provisoire est **supprimée** ;
   - sinon la phrase provisoire est conservée **jusqu'au premier démarrage** ;
   - si cette étape échoue, **l'installation s'arrête** plutôt que de laisser la phrase provisoire active.
3. **Premier démarrage** (assistant) : sans TPM, l'administrateur choisit sa **phrase de démarrage** (12 caractères au moins) et la phrase
   provisoire est supprimée. La clé de récupération est affichée, à conserver **hors du serveur** ; elle est réaffichée tant que l'administrateur
   ne confirme pas l'avoir enregistrée, puis sa copie locale est effacée.
4. **Ensuite** : menu console « Chiffrement du disque » : état, et création d'une nouvelle clé de récupération (l'ancienne est révoquée ;
   autorisée par le TPM seul, ou par la phrase actuelle sans TPM).

## Emplacements de clés (LUKS2)

| Jeton | Contenu | Présent |
|---|---|---|
| `ollamabuntu-recovery` | clé de récupération | toujours |
| `clevis` (tpm2) | clé scellée par le TPM | si TPM |
| `ollamabuntu-passphrase` | phrase de démarrage choisie | sans TPM, après l'assistant |
| `ollamabuntu-temp` | phrase provisoire de l'ISO | sans TPM, jusqu'à l'assistant |

## Rouvrir le disque avec la clé de récupération

Depuis un système de secours : `cryptsetup open /dev/<volume LUKS> dm_crypt-0` puis saisir la clé telle qu'affichée (avec les tirets).

## Limites

- Le déverrouillage par TPM est lié à l'**état du démarrage sécurisé** (PCR 7) : il protège contre le vol du **disque seul**, pas contre quelqu'un
  qui démarre la machine entière ; en BIOS ou sans Secure Boot, la protection est très faible.
- Sans TPM, la phrase est demandée **à chaque démarrage**, y compris après une coupure de courant.
- Non vérifié sur une installation réelle : que l'installeur accepte la phrase avec le choix « plus grand disque » ; la détection du volume
  chiffré dans l'environnement de fin d'installation ; le déverrouillage automatique par TPM dans l'initramfs au démarrage.
- La **mise à jour depuis l'ISO au démarrage** d'un système chiffré n'est pas prise en charge (un message l'indique) : mettre à jour depuis le
  serveur démarré (menu console ou console web).
- Entre l'installation et le premier passage de l'assistant (cas sans TPM), la phrase provisoire de l'ISO protège seule le disque.
