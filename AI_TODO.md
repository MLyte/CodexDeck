# AI_TODO

## Objectif
- Construire un cockpit terminal robuste pour piloter Codex à partir d’un backlog `AI_TODO.md`.
- L’app est testable quand le noyau MVP est livré, que les tests ciblés passent, et que les scénarios smoke passent.
- Machine d’état cible MVP: `IDLE -> STARTING -> RUNNING -> STOPPING -> IDLE|ERROR`.
- Invariants obligatoires: un seul process enfant actif, aucune transition implicite, tout run possède un `run_id`, tout état terminal écrit une ligne de log finale.

## Consolidation Tech Lead Produit
- Critique: le backlog couvre bien le périmètre, mais il doit guider Codex par incréments livrables plutôt que par alphabet seul.
- Découpage: le MVP doit rester limité au cockpit utilisable localement; la V2 absorbe les endpoints, la rotation avancée, la recherche logs et l’observabilité étendue.
- Dépendances: ne pas démarrer l’UI avancée avant le runner process, la machine d’état et les logs.
- Lisibilité: chaque tâche doit rester testable par un critère court; les détails longs vont dans README/tests, pas dans ce fichier.

## Ordre d’implémentation recommandé
1. Fondation testable: A, B01, B04, C, D, E, G, U01.
2. Cycle process: F, H, I, J, K01, K03.
3. TUI MVP: M, N, O, P, K02.
4. Tests et smoke: R01-R09, T01-T05, W03-W08, X02-X04, Z01-Z03.
5. Finition livraison: W, X01, Y.
6. V2 seulement après Go MVP: L, S, V01-V03, V06, Q03, O03.

## Definition of Done MVP
- Toutes les tâches `P0` marquées `MVP` sont terminées.
- Un seul process Codex peut tourner, y compris après appuis répétés sur `r`.
- `r`, `s`, `q` fonctionnent sans bloquer l’UI.
- `AI_TODO.md` est relu automatiquement après modification.
- Les logs sont visibles live dans la TUI et persistés dans `logs/agent.log`.
- Les erreurs de lancement et de fin process non-zéro sont affichées et comptabilisées.
- Les tests unitaires critiques et les smoke tests MVP passent avec un stub Codex local.

## Dépendances critiques
- `F01` dépend de `B04`, `D01`, `D02`, `D04`, `E01`, `G01`.
- `M01` dépend de `F01`, `K01`, `O01`.
- `T01` dépend de `W03` et fournit le stub utilisé par `T02` à `T05`.
- `T02` dépend de `C01`, `F01`, `K03`, `M01`, `O01`, `T01`.
- `T03` dépend de `F03`, `H01`, `H02`, `T01`.
- `T04` dépend de `I01`, `I02`, `T01`.
- `Z01` dépend de `R01` à `R09`.
- `Z02` dépend de `T01` à `T05`.

## Conventions
- Format: `- [ ] X99 [P0][MVP] Tâche courte mesurable`.
- `[x]` = terminé.
- `P0` bloquant production / fondation, `P1` important, `P2` amélioration.
- Une tâche sans critère testable implicite doit être reformulée avant exécution.
- Codex doit traiter les tâches dans l’ordre recommandé ci-dessus, pas strictement de A à Z.
- Chaque tâche exécutable par agent doit préciser au moins: fichier(s) attendus, comportement observable, test automatisé ou smoke associé.
- Une tâche est terminée uniquement si son résultat est vérifiable par une commande locale ou un scénario manuel court.
- Les tests automatisés ne doivent jamais dépendre du vrai binaire `codex`: utiliser `FakePopen`, scripts stubs et répertoires temporaires.
- Ordre de validation obligatoire: unitaires -> intégration process mocké -> smoke stub local -> smoke manuel Codex réel.

## Critique QA automation Python
- Le backlog couvre le périmètre fonctionnel, mais plusieurs tâches restent trop descriptives pour être exécutées automatiquement.
- Les critères d'acceptation doivent être exprimés en signaux mesurables: état attendu, fichier créé, ligne de log attendue, compteur incrémenté, code retour.
- Les dépendances de tests doivent être explicites: `pytest`, mock `subprocess.Popen`, `tmp_path`, monkeypatch env, fake terminal size, fake key reader.
- La CI doit lancer une suite rapide sans terminal interactif et sans Codex installé.
- Les smoke tests doivent utiliser un stub Python local capable de produire stdout, exit code 0/1, blocage volontaire et sortie volumineuse.
- Les tâches critiques doivent être validées dans l'ordre suivant: parser -> commande -> runner -> state machine -> logs -> UI non bloquante -> smoke.

## Commandes de validation cible
- Unitaires: `python -m pytest tests/unit -q`
- Intégration: `python -m pytest tests/integration -q`
- Smoke stub: `python -m pytest tests/smoke -q`
- Suite locale complète: `python -m pytest -q`
- Smoke manuel Windows: `$env:CODEX_CMD="python tests/stubs/codex_stub.py --mode success {todo}"; python codexdeck.py`

### A) Architecture de base [P0][MVP]
- [x] A01 [P0][MVP] Définir un contrat d’exigences minimal (lancement, stop, état, parsing TODO, logs).
- [x] A02 [P0][MVP] Figer le format d’entrée `AI_TODO.md` et la sémantique des cases `[ ]` / `[x]`.

### B) Configuration [P0][MVP]
- [x] B01 [P0][MVP] Externaliser les options clés via `CODEX_CMD`, `CODEX_MODEL`, `RUN_TIMEOUT_SECONDS`, `STATE_REFRESH_HZ`, `MAX_LOG_LINES`.
- [ ] B02 [P2][V2] Ajouter un fichier `codexdeck.conf` optionnel, priorités: CLI > env > défaut.
- [x] B03 [P1][MVP] Ajouter une commande `--print-config` masquant les valeurs sensibles et affichant les chemins résolus.
- [x] B04 [P0][MVP] Centraliser la config dans une dataclass `CockpitConfig` validée au démarrage (`todo_path`, `log_path`, `codex_cmd`, `model`, `run_timeout`, `stop_timeout`, `refresh_hz`, `max_log_lines`).
- [ ] B05 [P0][MVP] Refuser une config invalide avec message utilisateur clair avant de démarrer la TUI.

### C) Parsing des tâches [P0][MVP]
- [x] C01 [P0][MVP] Rendre le parser compatible avec `- [ ]`, `* [x]`, indents et sections.
- [x] C02 [P0][MVP] Ignorer proprement les lignes invalides et logger un warning sans crash.
- [x] C03 [P1][MVP] Ajouter des métadonnées de tâche (`id`, `line`, `raw`) stables.
- [x] C04 [P0][MVP] Définir un modèle `TodoTask(id, text, done, line, section, raw)` et interdire à la UI de parser directement le markdown.
- [x] C05 [P1][MVP] Utiliser un hash stable (`line + raw` au MVP) pour détecter les changements sans dupliquer les tâches.

### D) Machine d’état [P0][MVP]
- [x] D01 [P0][MVP] Formaliser l’`Enum` d’état: `IDLE`, `STARTING`, `RUNNING`, `STOPPING`, `ERROR`.
- [x] D02 [P0][MVP] Empêcher les transitions illégales (ex: `RUNNING` -> `RUNNING`).
- [x] D03 [P0][MVP] Représenter le timeout comme cause d’erreur (`error_code=RUN_TIMEOUT`) plutôt que comme état long-lived.
- [x] D04 [P0][MVP] Implémenter une table de transitions autorisées et des tests unitaires couvrant transitions valides/invalides.
- [x] D05 [P0][MVP] Normaliser les erreurs d’état (`INVALID_TRANSITION`, `PROCESS_ALREADY_RUNNING`, `PROCESS_NOT_RUNNING`).

### E) Contexte d’exécution [P0][MVP]
- [x] E01 [P0][MVP] Ajouter un contexte run (`run_id`, `pid`, `start_ts`, `last_error`) exposable à la UI.
- [x] E02 [P1][MVP] Calculer `uptime` et durée du run courant dans la status bar.

### F) Runner de process [P0][MVP]
- [x] F01 [P0][MVP] Encapsuler le cycle process dans une classe `CodexProcessRunner` (`start/stop/status/wait`).
- [x] F02 [P0][MVP] Interdire les lancements concurrents (`1 process max`) de bout en bout.
- [x] F03 [P1][MVP] Garantir retour propre des erreurs `Popen` vers état `ERROR` avec compteur.
- [x] F04 [P0][MVP] Définir une interface fakeable `ProcessHandle` minimale (`pid`, `stdout`, `poll`, `terminate`, `kill`, `wait`) pour tester sans lancer Codex.
- [x] F05 [P0][MVP] Injecter la factory de process dans `CodexProcessRunner` au lieu d’appeler `subprocess.Popen` directement dans la logique métier.

### G) Construction de la commande [P0][MVP]
- [x] G01 [P0][MVP] Séparer interpolation (`{todo}` / `$TODO` / `%TODO%`) et parsing d’arguments.
- [x] G02 [P0][MVP] Supporter arguments avec espaces et caractères spéciaux.
- [x] G03 [P1][MVP] Autoriser un mode stub de test (simuler Codex via script local).
- [x] G04 [P0][MVP] Exécuter les commandes avec `shell=False` par défaut et documenter explicitement que `CODEX_CMD` est parsé en arguments.
- [x] G05 [P0][MVP] Rejeter une commande vide, un placeholder TODO absent si requis, ou un chemin TODO inexistant avant `Popen`.

### H) Gestion d’erreurs process [P0][MVP]
- [x] H01 [P0][MVP] Afficher un message d’erreur court + root-cause dans le panneau logs.
- [x] H02 [P0][MVP] Incrémenter `errors` et revenir proprement à `IDLE`/`ERROR`.
- [ ] H03 [P1][V2] Classifier erreurs réessayables vs non réessayables.

### I) Arrêt propre [P0][MVP]
- [x] I01 [P0][MVP] Implémenter `terminate` puis `kill` après timeout configurable.
- [x] I02 [P0][MVP] Garantir la fermeture du lecteur de logs et la libération des ressources.
- [ ] I03 [P1][V2] Ajouter stop via signal `SIGINT`/`Ctrl+C` avec restore TUI.

### J) Timeout d’exécution [P0][MVP]
- [x] J01 [P0][MVP] Timeout global run configurable; si dépassé: stop contrôlé, log `RUN_TIMEOUT`, état final `ERROR`.
- [x] J02 [P0][MVP] Tests de timeout via fake process qui bloque volontairement.

### K) Logs live et file [P0][MVP]
- [x] K01 [P0][MVP] Maintenir une queue thread-safe + limite de taille (éviter fuite mémoire).
- [ ] K02 [P0][MVP] Troncature visuelle propre côté TUI selon largeur.
- [x] K03 [P0][MVP] Enregistrer les logs avec horodatage dans `logs/agent.log` en mode append.
- [x] K04 [P1][MVP] Sanitiser les logs avant écriture fichier (masquer `token`, `api_key`, `password`, `secret`).

### L) Logs persistants [P1][V2]
- [ ] L01 [P1][V2] Ajouter rotation simple (taille max + nombre de backups).
- [ ] L02 [P1][V2] Préserver les anciens logs lors des redémarrages.
- [ ] L03 [P1][V2] Ajouter test pour append-only across runs.

### M) UI non bloquante [P0][MVP]
- [x] M01 [P0][MVP] Vérifier le render loop sans blocage clavier (polling non bloquant).
- [x] M02 [P0][MVP] Ajouter rafraîchissement à taux constant configurable (8-20 Hz).
- [x] M03 [P1][MVP] Ajouter fallback si taille terminal trop petite.
- [x] M04 [P0][MVP] Garantir restauration terminal en `finally` après `q`, exception, `Ctrl+C` ou crash process.
- [x] M05 [P1][MVP] Dégrader proprement le rendu sous taille minimale (`<80x20`): message compact + status + commandes essentielles.

### N) Rendu panneaux [P0][MVP]
- [ ] N01 [P0][MVP] Corriger les largeurs avec bordures stables (pas de caractères parasites).
- [ ] N02 [P0][MVP] Afficher titres, séparateur, et status bar au format stable.
- [ ] N03 [P1][MVP] Ajouter compteur de lignes visibles + mode défilement.
- [x] N04 [P0][MVP] Ajouter mode rendu ASCII fallback (`+---+`) si le terminal ne supporte pas correctement les bordures Unicode.
- [x] N05 [P1][MVP] Tester rendu 80x24, 100x30, 120x40 et fenêtre redimensionnée, sans chevauchement ni ligne plus longue que la largeur.
- [ ] N06 [P1][MVP] Tronquer avec ellipsis stable en largeur terminale réelle, y compris caractères larges/accents.

### O) Contrôles clavier [P0][MVP]
- [x] O01 [P0][MVP] `r` = run, `s` = stop, `q` = quit (comportement stable).
- [x] O02 [P1][MVP] Aide clavier (`?` / `h`) affichant les raccourcis.
- [ ] O03 [P1][V2] Ajout mode pause de scroll / freeze fenêtre.
- [x] O04 [P0][MVP] Implémenter un lecteur clavier cross-platform isolé (`msvcrt` Windows, `termios/select` Unix) avec tests conditionnels.
- [ ] O05 [P1][MVP] Ajouter confirmations uniquement pour actions destructrices ou ambiguës, sans bloquer le render loop.
- [x] O06 [P1][MVP] Gérer touches inconnues sans bruit excessif: pas de crash, message bref optionnel.

### P) Rafraîchissement TODO [P0][MVP]
- [x] P01 [P0][MVP] Rechargement automatique à la modification du fichier (mtime + debounce).
- [x] P02 [P1][MVP] Rechargement manuel via touche dédiée.
- [ ] P03 [P2][V2] Diff visuel des tâches ajoutées/supprimées.

### Q) Observabilité [P1][V2]
- [x] Q01 [P1][V2] Exposer métriques simples: `runs_total`, `runs_success`, `runs_fail`, `errors_total`.
- [x] Q02 [P1][V2] Historique run courant dans la status bar/log.
- [ ] Q03 [P2][V2] Endpoint local debug (facultatif) pour état JSON.

### R) Vérification de robustesse [P1][MVP]
- [x] R01 [P0][MVP] Créer l'ossature `tests/unit`, `tests/integration`, `tests/smoke`, `tests/stubs` — AC: `python -m pytest -q` découvre les tests sans erreur d'import.
- [x] R02 [P0][MVP] Ajouter fixtures communes (`tmp_path`, `AI_TODO.md` temporaire, `logs/agent.log` temporaire, env isolé) — AC: aucun test n'écrit dans le vrai `logs/agent.log`.
- [x] R03 [P0][MVP] Tests unitaires parser TODO — AC: couvre `- [ ]`, `- [x]`, `* [X]`, indentation, sections, lignes invalides, fichier absent.
- [x] R04 [P0][MVP] Tests unitaires `build_command` — AC: couvre commande par défaut, commande vide rejetée, `{todo}`, `$TODO`, `%TODO%`, arguments avec espaces.
- [x] R05 [P0][MVP] Tests unitaires state machine — AC: transitions légales acceptées, transitions illégales refusées avec erreur contrôlée.
- [x] R06 [P0][MVP] Tests unitaires runner avec `FakePopen` — AC: start success, `Popen` exception, exit code 0, exit code non-zero, stop terminate, fallback kill.
- [x] R07 [P0][MVP] Tests logs et queue — AC: stdout fake horodaté, envoyé à la queue, écrit en append, limite de queue respectée.
- [x] R08 [P1][MVP] Tests rendu TUI pur — AC: rendu ne crashe pas à 60/80/120 colonnes, status bar contient state/model/errors.
- [x] R09 [P1][MVP] Tests boucle non bloquante avec fake key reader — AC: séquence `r`, `s`, `q` termine sans attendre une vraie entrée clavier.
- [x] R10 [P1][MVP] Test de restauration terminal après exception simulée pendant la boucle UI — AC: cleanup appelé en `finally`.
- [ ] R11 [P1][V2] Tests multi-OS ciblés (`msvcrt`/`tty`) — AC: tests conditionnels par plateforme documentés et stables en CI.

### S) Tuiles de logs + replay [P1][V2]
- [ ] S01 [P1][V2] Ajouter un mode "last N lines" depuis le fichier de logs.
- [ ] S02 [P1][V2] Recherche textuelle légère dans la vue droite.

### T) Vérification smoke [P0][MVP]
- [x] T01 [P0][MVP] Créer `tests/stubs/codex_stub.py` — AC: modes `success`, `fail`, `sleep`, `spam` produisent stdout déterministe et exit code attendu.
- [x] T02 [P0][MVP] Smoke stub success — AC: parse TODO -> run stub success -> logs visibles/persistés -> retour `IDLE` -> `errors=0`.
- [x] T03 [P0][MVP] Smoke stub fail — AC: run stub fail -> message `[ERROR]` visible -> état `ERROR` ou retour contrôlé -> `errors=1` -> nouveau run possible.
- [x] T04 [P0][MVP] Smoke stop — AC: run stub `sleep` -> stop -> terminate puis cleanup -> pas de process enfant restant.
- [x] T05 [P1][MVP] Smoke charge logs — AC: run stub `spam` produit beaucoup de lignes, l'UI reste réactive et la queue ne dépasse pas `MAX_LOG_LINES`.
- [ ] T06 [P1][MVP] Smoke refresh TODO — AC: modifier `AI_TODO.md` pendant la boucle met à jour la liste sans redémarrer l'app.

### U) Qualité code [P1][MVP]
- [x] U01 [P0][MVP] Refactor en couches testables `core` + `runner` + `ui` + `io` — AC: parser, commande, runner et rendu sont appelables sans terminal interactif.
- [ ] U02 [P1][MVP] Ajouter docstrings et annotations de type essentielles — AC: les interfaces publiques (`Config`, `Task`, `Runner`, `Cockpit`) sont typées.
- [ ] U03 [P1][MVP] Rendre les dépendances injectables — AC: horloge, filesystem, env, terminal size, key reader et `Popen` sont remplaçables en test.
- [ ] U04 [P2][V2] Nettoyage dette actuelle (`_truncate`, noms variables, séparation responsabilités) — AC: aucune logique process dans le rendu UI.

### V) Résilience UX [P1][V2]
- [ ] V01 [P1][V2] Gestion du mode terminal redimensionné en live.
- [ ] V02 [P2][V2] Indication de progression visuelle (`RUNNING...`).
- [ ] V03 [P2][V2] Messages d’erreur contextuels avec action suggérée.
- [ ] V04 [P1][MVP] Prévoir mode accessible sans couleur: états lisibles via texte/symboles, pas uniquement via couleur.
- [ ] V05 [P1][MVP] Respecter `NO_COLOR` et ajouter option `FORCE_COLOR=1` pour environnements compatibles.
- [ ] V06 [P2][V2] Ajouter thème contraste élevé pour consoles Windows et terminaux sombres/clairs.

### W) Packaging / runbook [P1][MVP]
- [x] W01 [P1][MVP] Script de lancement fiable (`python -m` ou `.\codexdeck.py`).
- [x] W02 [P1][MVP] Ajouter `.gitignore` pour éviter le bruit logs locaux.
- [x] W03 [P1][MVP] Ajouter configuration test minimale (`pyproject.toml` ou équivalent) — AC: `python -m pytest -q` fonctionne depuis la racine repo.
- [x] W04 [P1][MVP] Ajouter CI GitHub Actions Python — AC: checkout, setup-python, install deps, pytest unit+integration sans Codex réel.
- [x] W05 [P1][MVP] Ajouter `requirements.txt` ou `pyproject.toml` minimal — AC: installation reproductible sur environnement propre.
- [x] W06 [P1][MVP] Ajouter scripts locaux `scripts/dev.ps1`, `scripts/smoke.ps1`, `scripts/test.ps1` avec codes retour non-zero en cas d'échec.
- [x] W07 [P1][MVP] Ajouter un stub Codex local pour smoke tests sans dépendre du vrai binaire `codex`.
- [x] W08 [P1][MVP] Documenter et tester la création automatique de `logs/` si le dossier est absent.
- [ ] W09 [P2][V2] Préparer packaging simple (requirements/venv lock, entrypoint).

### X) Documentation [P0][MVP]
- [x] X01 [P0][MVP] Mettre à jour `README.md` avec modes d’usage, variables env, commandes, troubleshooting.
- [x] X02 [P1][MVP] Ajouter mini-guide de test (`pytest`, smoke, scénarios manuels).
- [x] X03 [P1][MVP] Documenter stratégie de mocks — AC: README explique comment tester sans Codex réel avec `FakePopen` et `tests/stubs/codex_stub.py`.
- [x] X04 [P1][MVP] Documenter ordre de validation release — AC: unitaires, intégration, smoke stub, smoke manuel listés avec commandes.
- [x] X05 [P1][MVP] Ajouter section "Quickstart Windows" avec commandes PowerShell depuis clone frais jusqu'au smoke test.
- [x] X06 [P1][MVP] Ajouter section "Dépannage" couvrant `codex` introuvable, permissions logs, terminal trop petit, commande invalide.
- [ ] X07 [P2][V2] Ajouter schéma d'architecture (inputs/outputs/state machine).

### Y) Conformité locale / qualité de repo [P1][MVP]
- [x] Y01 [P1][MVP] Vérifier ligne fine encodage et chemins `logs/agent.log`.
- [x] Y02 [P1][MVP] Ajouter garde-fou d’encodage UTF-8 partout.
- [ ] Y03 [P2][V2] Prévoir stratégie de secrets si l’environnement nécessite tokens.
- [x] Y04 [P1][MVP] Documenter compatibilité console: Windows Terminal, PowerShell, cmd, Git Bash, Linux/macOS terminal.
- [x] Y05 [P1][MVP] Normaliser fins de ligne et encodage (`.gitattributes`) pour éviter écarts Windows/Unix.
- [x] Y06 [P1][MVP] Ajouter contrôle de git hygiene: `logs/*.log`, caches Python, venv et artefacts locaux exclus du repo.
- [x] Y07 [P1][MVP] Ajouter scan sécurité minimal dans `scripts/test.ps1` pour détecter secrets évidents dans logs et fichiers suivis.
- [x] Y08 [P1][MVP] Garantir que les chemins fichier sont relatifs au dossier projet ou configurables, jamais codés en absolu.

### Backend DoD MVP
- [x] BD01 [P0][MVP] Tous les composants core sont testables sans terminal interactif et sans process Codex réel.
- [ ] BD02 [P0][MVP] Les erreurs utilisateur ont un `error_code`, un message court, et une cause technique loggée.
- [x] BD03 [P0][MVP] Aucun thread lancé par un run ne reste vivant après `stop`, timeout ou fin normale.
- [x] BD04 [P0][MVP] Les tests couvrent parser, config, command builder, state machine, process runner, log queue.

### Z) Finalisation MVP -> V2 [P0][MVP]
- [x] Z01 [P0][MVP] Critères Go/No-Go automatisés — AC: `python -m pytest -q` passe et couvre parser, commande, runner, state machine, logs.
- [x] Z02 [P0][MVP] Critères Go/No-Go smoke — AC: success/fail/stop/spam passent avec stub local et aucun process résiduel.
- [ ] Z03 [P0][MVP] Critères Go/No-Go manuel — AC: lancer l'app, appuyer `r`, voir logs live, `s` stoppe, `q` quitte, terminal restauré.
- [x] Z04 [P1][MVP] Faire le point qualité: revue de checklist complète + correction des écarts.
- [ ] Z05 [P1][V2] Gate V2: politiques de timeout avancées + modèle low tokens + stop amélioré + observabilité avancée.
