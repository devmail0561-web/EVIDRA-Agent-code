# ADR-0003 — Single-writer + file d'événements

- Date : 2026-10-11
- Statut : accepté
- Fonde : ETUDE_SA.md §27 / PLAN_SA.md §3.2, §3.4 (T1.5, T8.1)

## Contexte

Le scheduler (thread propriétaire de la mémoire) et l'API HTTP (thread/event
loop séparé) accèdent au même état. Des verrous fins = risque de deadlock et
audit difficile.

## Décision

Un seul thread écrit dans la mémoire. L'API dépose un événement (P1–P3) dans
une file thread-safe avec `Future`, que le scheduler traite dans l'ordre de
priorité (réveil immédiat, latence ≤ un tick).

## Conséquences

Cohérence sans verrou applicatif ; test de charge concurrente en T8.1 ;
aucun appel lourd dans le thread scheduler (worker + timeout, cf. patch P3).

## Alternative rejetée

Multi-thread avec locks fins — complexité et deadlocks pour aucun gain mesuré.
