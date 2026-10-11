# ADR-0005 — Découverte par entry-points stdlib

- Date : 2026-10-11
- Statut : accepté
- Fonde : ETUDE_SA.md §23 / PLAN_SA.md §3.4 (T1.3)

## Contexte

Le noyau ne doit référencer aucun nom concret d'outil/adaptateur (I2), tout
en restant plug-and-play. Côté moteur : zéro entry-point existant, départ de
zéro sans antériorité.

## Décision

Découverte via `importlib.metadata.entry_points` (stdlib), groupes
`evidra_tools` / `evidra_adapters`. Cycle de vie
`discovered → validated → enabled → running → disabled | quarantined`.

## Conséquences

Ajouter un plugin = un paquet + un manifeste, jamais une modification du
noyau (test de non-régression T1.7).

## Alternative rejetée

Registre codé en dur / décorateur `@register` — noms concrets dans le noyau.
