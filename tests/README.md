# Tests

| Dossier | Contenu | Portable ? |
|---|---|---|
| `unit/` | Tests sans dépendance à un banc particulier : choix du serveur par le routeur (répartition de charge) et masquage des extraits de demandes, réglage automatique des GPU AMD, moteur du chiffrement du disque (LUKS2 réel + TPM logiciel `swtpm`), mise à jour en ligne (faux GitHub local, signatures, falsifications, routes de la console : `online_update_test.py` ; écran de la console en français et en anglais, jsdom : `online_update_ui_test.js`). | Oui |
| `bench/` | Banc de régression complet de l'auteur (API, interface simulée avec jsdom, pare-feu dans un espace réseau isolé, vrais services Ollama, assistant console piloté dans un pseudo-terminal, démarrage QEMU BIOS/UEFI). | **Non** : voir ci-dessous |

## Tests portables

```sh
make test          # ou, séparément :
python3 tests/unit/router_balance_test.py
python3 tests/unit/gpu_auto_test.py
bash    tests/unit/crypt_engine_test.sh      # nécessite : cryptsetup, swtpm, tpm2-tools, clevis
python3 tests/unit/online_update_test.py     # nécessite : openssl
npm install --no-save jsdom@24 && make test-ui   # console web (mise à jour en ligne)
make i18n-check    # le catalogue anglais est-il à jour par rapport à tools/i18n/ ?
make lint          # shellcheck
```

## Banc de régression de l'auteur

`bench/tmp/` reproduit l'arborescence `/tmp` de l'environnement où le projet est développé : les scripts s'y
appellent par chemins absolus (`/tmp/bench/run.sh`, `/tmp/uitest/ui7.js`, `/tmp/wz/drive.py`…). Il suppose
en outre des éléments qui **ne sont pas dans ce dépôt** : un système de test (`/tmp/target`, une arborescence
Ubuntu où l'appliance est installée), une ISO Ubuntu réduite (`/tmp/fakeiso`), un faux matériel GPU (`/tmp/gpufake`),
Node.js avec `jsdom`, QEMU/OVMF, et un vrai Ollama avec quelques petits modèles.

Il est conservé ici comme documentation exécutable de ce qui est vérifié (chaque test porte une phrase qui dit ce
qu'il prouve) et comme point de départ pour une intégration continue, mais il n'est pas lançable tel quel ailleurs.
Un échec de test y est d'abord soupçonné d'être faux, puis diagnostiqué avant toute correction ; les tests vérifient
un format plutôt qu'une version amont précise.

> Lancez les tests avec `PYTHONDONTWRITEBYTECODE=1` : sinon Python écrit des fichiers `__pycache__` à côté des sources de `src/`
> (ignorés par git et écartés de l'ISO par la construction, mais inutiles).
