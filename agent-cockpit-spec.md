# Agent Cockpit — Cahier des charges

## Objectif
Créer une app terminal (TUI) permettant de piloter un agent Codex basé sur AI_TODO.md.

## Interface

┌──────────────────────────────┬────────────────────────────────────────────┐
│ AI_TODO.md                   │ Codex Output                               │
│                              │                                            │
│ [x] Task 1                   │ > Running Codex...                         │
│ [ ] Task 2                   │ > Reading files...                         │
│ [ ] Task 3                   │ > Editing start-service.bat                │
│                              │                                            │
├──────────────────────────────┴────────────────────────────────────────────┤
│ Status: IDLE | Model: normal | Last run: 21:42 | Errors: 0                │
└───────────────────────────────────────────────────────────────────────────┘

## MVP Features
- Lecture et parsing de AI_TODO.md
- Affichage des tâches
- Lancement manuel de Codex
- Affichage live des logs
- Status bar

## V2
- Stop process
- Timeout auto
- Switch modèle low tokens
- Logs persistants

## Architecture
Entrées:
- AI_TODO.md
- logs/agent.log

Sorties:
- stdout Codex → UI
- logs fichier

## Machine d’état
IDLE → RUNNING → IDLE / ERROR

## Contraintes
- 1 process Codex max
- UI non bloquante

## Fichiers
- agent-cockpit.py
- AI_TODO.md
- logs/
