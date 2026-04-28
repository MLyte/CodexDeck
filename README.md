# Agent Cockpit

Terminal UI (TUI) légère pour piloter un process Codex basé sur un fichier `AI_TODO.md`.

## Vue d'ensemble

Ce projet fournit une interface console en deux panneaux :

- gauche : tâches parsées depuis `AI_TODO.md`
- droite : sorties live de `Codex`
- barre d'état : `Status`, modèle courant, dernière exécution, nombre d'erreurs

Machine d'état minimale :

- `IDLE`
- `RUNNING`
- `ERROR`

## Fichiers

- `agent-cockpit.py` : application TUI
- `AI_TODO.md` : plan de tâches au format checklist
- `logs/agent.log` : journal append-only des sorties Codex

## Format de `AI_TODO.md`

Le parseur lit les lignes au format checklist :

```md
- [ ] Tâche non faite
- [x] Tâche faite
```

Le fichier est relu automatiquement lorsqu’il change.

## Démarrage

```powershell
python agent-cockpit.py
```

Pré-requis : Python 3.9+

## Contrôles clavier

- `r` : lancer Codex
- `s` : arrêter le process en cours
- `q` : quitter l'application

## Variables d'environnement (optionnelles)

- `CODEX_CMD` : commande utilisée pour démarrer Codex.  
  Exemples :
  - `codex`
  - `codex run`
- `CODEX_MODEL` : nom de modèle affiché dans la status bar (valeur affichée seulement, par défaut `normal`).

## Sorties

Tous les logs de Codex sont :

- affichés en direct dans la zone droite de la TUI
- écrits en append dans `logs/agent.log`

## Note

Le MVP couvre la lecture/parsing de `AI_TODO.md`, l’exécution manuelle, l’affichage live et une barre de statut non bloquante.
Les points V2 (timeout auto, switch modèle low tokens, etc.) sont faciles à ajouter dans l’étape suivante.
