# CodexDeck

CodexDeck est une app terminal en cours de développement pour piloter Codex depuis un fichier `AI_TODO.md`.

L’objectif est simple: garder le plan de travail à gauche, voir la sortie Codex en direct à droite, et contrôler un unique process Codex sans bloquer le terminal.

```text
┌──────────────────────────────┬────────────────────────────────────────────┐
│ AI_TODO.md                   │ Codex Output                               │
│                              │                                            │
│ [x] Task 1                   │ > Running Codex...                         │
│ [ ] Task 2                   │ > Reading files...                         │
│ [ ] Task 3                   │ > Editing codexdeck.py                     │
│                              │                                            │
├──────────────────────────────┴────────────────────────────────────────────┤
│ Status: IDLE | Model: normal | Last run: 21:42 | Errors: 0                │
└───────────────────────────────────────────────────────────────────────────┘
```

## Statut

CodexDeck est un MVP actif. Le premier prototype existe déjà; le backlog technique détaillé vit dans `AI_TODO.md`.

Le cap MVP:

- parser `AI_TODO.md`
- afficher les tâches et les logs en TUI
- lancer, suivre et arrêter un seul process Codex
- persister les logs dans `logs/agent.log`
- rendre le noyau testable sans vrai binaire `codex`
- valider le comportement avec tests unitaires, intégration et smoke stub

## Démarrage

Pré-requis: Python 3.9+.

```powershell
python codexdeck.py
```

Afficher la configuration résolue:

```powershell
python codexdeck.py --print-config
```

Ancien point d’entrée encore disponible pendant la transition:

```powershell
python agent-cockpit.py
```

## Contrôles

- `r`: lancer Codex
- `s`: arrêter le process actif
- `q`: quitter CodexDeck

## Configuration

CodexDeck lit principalement sa configuration depuis l’environnement.

- `CODEX_CMD`: commande utilisée pour lancer Codex, par défaut `codex {todo}`
- `CODEX_MODEL`: nom affiché dans la status bar, par défaut `normal`
- `RUN_TIMEOUT_SECONDS`: timeout cible du run Codex
- `STOP_TIMEOUT_SECONDS`: délai avant `kill` après un `terminate`
- `STATE_REFRESH_HZ`: fréquence cible de rafraîchissement UI
- `MAX_LOG_LINES`: limite cible de lignes gardées en mémoire
- `CODEX_TODO_PATH` / `TODO_PATH`: chemin du backlog, par défaut `AI_TODO.md`
- `CODEX_LOG_PATH` / `LOG_PATH`: chemin du log persistant, par défaut `logs/agent.log`
- `CODEX_ASCII_BORDERS=1`: force les bordures ASCII (`+---+`) pour les terminaux qui affichent mal l’Unicode

Exemple avec un stub local:

```powershell
$env:CODEX_CMD="python tests/stubs/codex_stub.py --mode success {todo}"
python codexdeck.py
```

## Backlog Piloté Par IA

`AI_TODO.md` est à la fois l’entrée produit et le plan d’exécution technique.

Il décrit:

- l’ordre d’implémentation recommandé
- la Definition of Done MVP
- les dépendances critiques
- les tâches A à Z
- les tests attendus
- les gates Go/No-Go

La machine d’état cible MVP est:

```text
IDLE -> STARTING -> RUNNING -> STOPPING -> IDLE|ERROR
```

Invariants clés:

- un seul process enfant actif
- aucun run sans `run_id`
- aucune transition d’état implicite
- chaque état terminal écrit une ligne de log finale

## Architecture Cible

Le backlog pousse le code vers quatre couches testables:

- `core`: config, modèle de tâche, machine d’état
- `runner`: lifecycle process Codex
- `ui`: rendu terminal, clavier, status bar
- `io`: fichiers, logs, sanitisation

Cette séparation doit permettre de tester le coeur sans terminal interactif et sans lancer réellement Codex.

## Tests Cibles

Installer les dépendances de test:

```powershell
python -m pip install -r requirements.txt
```

Commandes locales:

```powershell
python -m pytest tests/unit -q
python -m pytest tests/smoke -q
python -m pytest -q
powershell -ExecutionPolicy Bypass -File scripts\test.ps1
powershell -ExecutionPolicy Bypass -File scripts\smoke.ps1
```

Les tests ne dépendent pas du vrai binaire `codex`. Ils utilisent `FakePopen`, des répertoires temporaires et `tests/stubs/codex_stub.py`.

Ordre de validation release:

1. Unitaires: parser, config, commande, state machine, runner, logs.
2. Smoke stub: success, fail, stop, spam.
3. Smoke manuel: définir `CODEX_CMD` vers le stub, lancer `python codexdeck.py`, appuyer sur `r`, `s`, puis `q`.

Exemple smoke manuel Windows:

```powershell
$env:CODEX_CMD="python tests/stubs/codex_stub.py --mode success {todo}"
python codexdeck.py
```

## Fichiers

- `codexdeck.py`: commande officielle CodexDeck
- `agent-cockpit.py`: prototype TUI historique, conservé comme compatibilité
- `codexdeck_core.py`: config, parser TODO, commande, machine d’état
- `codexdeck_runner.py`: lifecycle process, logs bornés, stub-friendly
- `AI_TODO.md`: backlog détaillé et plan d’exécution
- `logs/agent.log`: logs persistants générés à l’exécution
- `tests/stubs/codex_stub.py`: stub Codex pour tests smoke
- `agent-cockpit-spec.md`: cahier des charges initial

## Roadmap Courte

- solidifier `CockpitConfig`
- isoler `CodexProcessRunner`
- rendre la state machine explicite
- ajouter le stub Codex et la suite `pytest`
- améliorer le rendu terminal multi-tailles
- ajouter `.gitignore`, `.gitattributes`, scripts PowerShell et CI

## Dépannage

- `codex` introuvable: définir `CODEX_CMD` avec un chemin valide ou installer le CLI Codex.
- commande invalide: lancer `python codexdeck.py --print-config` et vérifier `CODEX_CMD`; les arguments sont parsés puis exécutés avec `shell=False`.
- terminal trop petit: agrandir la fenêtre; le mode compact est prévu dans le backlog.
- logs absents: vérifier les droits d’écriture dans `logs/`; le dossier est créé automatiquement au lancement du runner.
- sortie illisible: le fallback ASCII et les modes `NO_COLOR` / `FORCE_COLOR` sont prévus dans le backlog.

## Compatibilité Console

Le lecteur clavier isole Windows (`msvcrt`) et Unix (`termios`/`select`). Le chemin principal visé est Windows Terminal ou PowerShell, avec tests automatisés sans terminal interactif.
