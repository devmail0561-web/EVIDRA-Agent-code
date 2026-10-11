# ADR-0004 — Noyau stdlib, Pydantic aux bords

- Date : 2026-10-11
- Statut : accepté
- Fonde : ETUDE_SA.md §13 / PLAN_SA.md §3.4 (T1.1, T4.1)

## Contexte

Le noyau (`kernel/`) doit rester < 500 SLOC, auditable, offline, sans
dépendance transitive : c'est le cœur testable du harness.

## Décision

Noyau en stdlib uniquement (`dataclasses`, `typing.Protocol`, …).
Pydantic v2 réservé aux bords : directive, manifestes, API.

## Conséquences

`mypy --strict` sur `kernel/` et `memory/` ; validation riche hors noyau ;
garde I2 (SLOC + noms concrets).

## Alternative rejetée

Pydantic partout — dépendance transitive dans le cœur, noyau non minimal.
