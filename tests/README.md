# Tests

| Dossier | Contenu | Portable ? |
|---|---|---|
| `unit/` | Tests sans dépendance à un banc particulier : choix du serveur par le routeur (répartition de charge) et masquage des extraits de demandes, réglage automatique des GPU AMD, moteur du chiffrement du disque (LUKS2 réel + TPM logiciel `swtpm`), mise à jour en ligne (faux GitHub local, signatures, falsifications, routes de la console : `online_update_test.py` ; écran de la console en français et en anglais, jsdom : `online_update_ui_test.js`). | Oui |
| `bench/` | Banc de régression complet de l'auteur (API, interface simulée avec jsdom, pare-feu dans un espace réseau isolé, vrais services Ollama, assistant console piloté dans un pseudo-terminal, démarrage QEMU BIOS/UEFI). | **Non** : voir ci-dessous |

## Tests portables

```sh
make test          # ou, séparément :
python3 tests/unit/router_balance_test.py
python3 tests/unit/router_limits_test.py    # routeur de bout en bout : plafond, file d'attente, quotas (faux Ollama)
python3 tests/unit/limits_test.py          # plafonds, quotas, règles de routage
python3 tests/unit/monitor_test.py         # débordement CPU/GPU, recommandations, alertes
python3 tests/unit/admin_features_test.py  # console : limites, règles, test du parc, alertes
python3 tests/unit/backup_test.py          # sauvegarde chiffrée, quantifications et VRAM
bash tests/unit/rollback_test.sh           # retour arrière (racine factice)
bash tests/unit/host_docker_test.sh        # construction en conteneur (Windows/macOS) : montage de la clé de signature (docker simulé)
node tests/unit/ops_ui_test.js             # console : nouveaux écrans (jsdom)
python3 tests/unit/batch2_test.py          # statistiques, export CSV, échéance des clés, Prometheus, GPU (routes HTTP réelles)
python3 tests/unit/router_expiry_test.py   # routeur : clé expirée refusée
bash tests/unit/gpu_ready_test.sh          # démarrage : attente et chargement des pilotes NVIDIA avant Ollama (racine factice)
python3 tests/unit/gpu_guard_test.py       # carte graphique disponible et associée à Ollama : diagnostic, réparation, SMART, RAID, Xid
python3 tests/unit/perf_test.py            # performances : mesure de débit, profils, préchauffage, garde-fou de débit, réglages système
python3 tests/unit/router_batch3_test.py  # routeur : affinité de session, plafonds de contexte et de sortie par clé (faux Ollama)
python3 tests/unit/catalog_sources_test.py  # catalogue « Recommandés » multi-registres (Ollama + Hugging Face, vue agrégée)
python3 tests/unit/ops3_test.py            # journal d'audit, rapport hebdomadaire par e-mail, espace disque des modèles (routes HTTP réelles)
node tests/unit/batch2_ui_test.js          # console : thème, cloche, statistiques, filtres, palette Ctrl+K (jsdom, FR et EN)
node tests/unit/batch3_ui_test.js          # console : Performance, disponibilité GPU, matériel, audit, rapport, espace disque, plafonds, catalogue multi-registres (jsdom, FR et EN)
python3 tests/unit/router_failover_test.py      # routeur : reprise automatique sur un autre serveur (vrais échanges HTTPS simulés), disjoncteur, requêtes sauvées
python3 tests/unit/queue_test.py                 # file d'attente : priorités, vieillissement, plafond global, file pleine, délai dépassé, routeur en vrais échanges HTTP
python3 tests/unit/privacy_test.py               # confidentialité : motifs (IBAN, carte, sécu, téléphone, e-mail, IP, secrets), anonymisation avant le modèle, termes interdits globaux et par clé, routeur de bout en bout
python3 tests/unit/privacy_admin_test.py         # confidentialité côté console : réglages, statistiques, essai, termes par clé, routes, audit
python3 tests/unit/rag_test.py                   # base de documents : extraction (texte, HTML, Word, OpenDocument, PDF), découpage, vecteurs, recherche exacte, citations, stockage
python3 tests/unit/rag_router_test.py            # base de documents par l'API : /rag/search et /rag/ask, droits, bases autorisées par clé, en-tête des sources (Ollama simulé)
python3 tests/unit/rag_admin_test.py             # base de documents côté console : dépôt, indexation en arrière-plan, réindexation, suppression, routes, audit
python3 tests/unit/power_test.py                 # réveil et veille du parc : paquet magique (envoi UDP réel sur la boucle locale), réglages, décisions de réveil et de mise en veille, cartes réseau
python3 tests/unit/power_admin_test.py           # réveil et veille côté console : réveil manuel et automatique, mise en veille à distance et autorisation du serveur, journal, routes, audit (parc simulé)
python3 tests/unit/power_router_test.py          # routeur : modèle que seul un serveur endormi possède (503 + Retry-After, signal lu par la console)
python3 tests/unit/redirect_router_test.py       # routeur : redirection de modèles (règles à chaud, pourcentage, OpenAI, pas d'enchaînement, journal)
python3 tests/unit/redirect_admin_test.py        # console : validation des règles, routes HTTP, droits, audit, sauvegarde
python3 tests/unit/fit_test.py                 # ajustement : mémoire du modèle (poids, cache de contexte, fenêtre glissante), scénarios (mémoire vidéo, experts en mémoire système, couches), vitesse estimée, calibrage, Hugging Face
python3 tests/unit/llamacpp_test.py            # moteur llama.cpp : nom du fichier du modèle, arguments de llama-server, options détectées, traduction Ollama <-> OpenAI (flux, outils, durées), choix de l'archive
python3 tests/unit/llama_engine_test.py        # service du moteur : démarrage à la demande (faux llama-server), arrêt sur inactivité, un moteur à la fois, annulation, erreurs, flux
python3 tests/unit/llama_admin_test.py         # console : routes /api/fit* et /api/llama*, installation (somme SHA-256, extraction sûre), moteurs, sauvegarde, audit, routeur
python3 tests/unit/sso_test.py                   # connexion unique : jetons OIDC (RS256, nonce, aud, exp), PKCE, LDAP/AD simulé (LDAPS, StartTLS, injection de filtre), rôles par groupe, comptes SSO, routes HTTP
python3 tests/unit/costs_test.py                 # coûts : temps de calcul, énergie, registre mensuel alimenté par le journal, équipes, export CSV, rapport hebdomadaire
python3 tests/unit/modelupdate_test.py          # mise à jour des modèles : fenêtre de maintenance, copie de sécurité, retour arrière automatique ou manuel (Ollama simulé)
python3 tests/unit/evals_test.py                  # laboratoire : critères, comparaison, jeux de tests, rejeu automatique (Ollama simulé)
node tests/unit/queue_ui_test.js             # console : Serveurs > File d'attente, protection de la carte graphique, priorité d'une clé, FR et EN
node tests/unit/privacy_ui_test.js           # console : Journaux > Confidentialité (statistiques, réglages, essai), termes interdits d'une clé, FR et EN
node tests/unit/rag_ui_test.js               # console : écran Documents (dépôt, progression, réglages, essai), base choisie dans la conversation avec sources, bases autorisées d'une clé, FR et EN
node tests/unit/power_ui_test.js             # console : Serveurs > Veille (réglages, états, journal, réveil et veille manuels), cartes réseau et autorisation de la gestion centralisée, FR et EN
node tests/unit/fit_ui_test.js               # console : Modèles > Ajustement et Moteur MoE (verdicts, détail, calibrage, Hugging Face, création/modification/arrêt des moteurs, installation), FR et EN
node tests/unit/redirect_ui_test.js          # console : Modèles > Redirections (règles, pourcentage, enregistrement, erreurs), FR et EN
node tests/unit/sso_ui_test.js               # console : bouton de la page de connexion, codes d'erreur, Utilisateurs > Connexion unique (SSO), comptes SSO, FR et EN
node tests/unit/costs_ui_test.js             # console : Journaux > Coûts (mois, équipes, clés, paramètres, export), équipe d'une clé, FR et EN
node tests/unit/modelupdate_ui_test.js      # console : Modèles > Mises à jour (réglages, vérification, retour arrière, historique) en jsdom, FR et EN
node tests/unit/lab_ui_test.js              # console : Laboratoire (comparateur, jeux de tests de non-régression) en jsdom, FR et EN
node tests/unit/modelmap_ui_test.js         # console : modèles de remplacement par listes déroulantes, proposition automatique (jsdom, FR et EN)
python3 tests/unit/hf_test.py            # recherche Hugging Face (faux serveur local)
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
