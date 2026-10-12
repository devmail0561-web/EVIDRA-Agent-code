# ADR-0012 — Chaînes Dijkstra via le CLI Rust (amende I1 pour `query_chain`)

- Date : 2026-10-12
- Statut : accepté
- Fonde : ETUDE_SA.md §7.2 opt.3 / PLAN_SA.md T5.2 + T5.4 (branche CLI)

## Contexte

L'acceptation T5.2 exige Dijkstra (3×0.90 bat direct 0.60). Constaté en main :
`reason()` Python = BFS sauts (direct gagne toujours) — inapte. Le binaire
`gcn` livré était périmé (02/10, avant Dijkstra-requête du 11/10) ; reconstruit
(`cargo build --release`), `CHAIN a -> b?` rend le 3-hop rank 1 (0.729) puis
le direct rank 2 (0.6) avec `ranked_paths`. Coût Dijkstra : `-ln(conf × poids
d'origine)` — d'où `origin: explicit` systématique à la sérialisation (sinon
pénalité 0.7 constatée), et la limite actée « 0.60 affiché peut devancer 0.73 ».

## Décision

`engine_bridge/rust.py` : `gcn query --ir F "CHAIN a -> b?"` en subprocess
(isolé, timeout directive, JSON validé, fail-closed, IR éphémère nettoyée,
labels anti-injection refusés). `tools/query_chain.py` consomme `links` +
`ranked_paths` ; SANS binaire : DEGRADE explicite (jamais de repli BFS qui
changerait la sémantique — ADR-10 respecté : Dijkstra consommé, pas réécrit).
Amende I1 : le whitelist couvre les IMPORTS ; le subprocess isolé avec timeout
et schéma validé est autorisé ici (même régime que T5.4 l'exigeait).

## Conséquences

`query_chain` dépend du binaire (comme la lattice : `trouver_binaire()`).
Suffixe `TOPK=` non fonctionnel côté CLI (constaté : erreurs de parse) — pas
de `top_k` exposé tant que le CLI ne l'accepte pas. CYCLES/GAPS restent au
spike T5.4. Champ `lang` de la réponse : rempli en dur par le moteur (gabarits
FR, Ph8 — pas notre IR) → le SA l'ignore, seule la provenance fait foi.

## Alternative rejetée

Approximation Python du ranking (seuils, BFS) — sémantique différente,
divergence garantie. Réimplémenter Dijkstra — interdit (ADR-10).
