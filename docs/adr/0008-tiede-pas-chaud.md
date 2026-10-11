# ADR-0008 — Tiède, pas chaud : code = restart, comportement = directive

- Date : 2026-10-11
- Statut : accepté
- Fonde : ETUDE_SA.md §23 / PLAN_SA.md §3.4 (T4.2)

## Contexte

Le WAL n'a ni lock inter-processus d'écriture partagée ni quiescence :
charger du code à chaud risquerait la corruption. Le restart est de toute
façon dominé par les chargements modèles (~25 s), incompressibles.

## Décision

Mise à jour de code = redémarrage. Mise à jour de comportement = directive
relue à chaque cycle (on/off de plugins sans restart — « tiède »). 90 % du
bénéfice, 0 % du risque. Chargement à chaud interdit avant P3 (gate T10.7).

## Conséquences

Directive invalide = rejetée, ancienne conservée + alerte ; plugin `disabled`
= code inerte.

## Alternative rejetée

Hot-reload — corruption prouvée sur WAL sans lock, gain nul (restart dominé
par les modèles).
