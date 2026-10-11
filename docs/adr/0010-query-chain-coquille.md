# ADR-0010 — `query_chain` coquille mince sur `reason()`, jamais de Dijkstra SA

- Date : 2026-10-11
- Statut : accepté
- Fonde : ETUDE_SA.md §7.2 opt.3 / PLAN_SA.md §3.4 (T3.5, T5.2)

## Contexte

Le BFS trouvait le chemin le plus court en sauts, pas le plus fiable. Le
moteur (Phase 3) fait désormais Dijkstra confiance-max (`-ln(conf)`, Yen
top-k) : toute réimplémentation côté SA serait une duplication divergente.

## Décision

`query_chain` = coquille mince sur `reason()` (budget 16, profondeur ≤ 2,
top-k 5, passés en arguments), sur sous-graphe borné. Logique nulle dans la
coquille ; résultats `derived` jamais ingérés.

## Conséquences

BFS bidirectionnel étudié (spike) uniquement si le SLO échoue sur chaînes
longues ; test d'intégration « 3×0.90 bat 1×0.60 ».

## Alternative rejetée

Dijkstra SA — duplication du moteur, divergence garantie.

## Point ouvert (T0.2)

La liste blanche I1 nomme `analyze`/`analyze_batch` (méthodes d'instance) mais
pas la classe `GCNEngine`, seul point de construction constaté
(`gcn_python.engine`, cf. docs/engine-compat.md). Garde T0.4 appliquée à la
lettre ; trancher avant T3.1 : autoriser `GCNEngine` en construction seule
dans `engine_bridge`, ou exiger une fabrique côté moteur.
