# ADR-0007 — Partitionnement par domaine dès le jour 1

- Date : 2026-10-11
- Statut : accepté
- Fonde : ETUDE_SA.md §7.2 opt.1 / PLAN_SA.md §3.4 (T2.4)

## Contexte

La mémoire n'est pas un graphe global : les requêtes d'un domaine ne doivent
jamais traverser les autres graphes. Toutes les optimisations (index,
Dijkstra, cache) opèrent sur le graphe de domaine — le partitionnement
multiplie leur gain.

## Décision

Un graphe par domaine dès le jour 1 (layout disque `domains/<d>/` + routage),
sous-domaines descriptif/normatif via champ `subdomain`.

## Conséquences

Refactor tardif évité ; test d'isolation (requête domaine A ≠ structures B).

## Alternative rejetée

Graphe global unique + refactor ultérieur — coût de migration prouvé élevé.
