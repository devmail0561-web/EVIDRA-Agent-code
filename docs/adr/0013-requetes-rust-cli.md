# ADR-0013 — Requêtes Rust via CLI isolé (spike T5.4 tranché : CLI seul)

- Date : 2026-10-12
- Statut : accepté
- Fonde : PLAN_SA.md T5.4 (spike exigé avant T5.5) / ETUDE_SA.md §7.1

## Contexte

`CYCLES?`/`GAPS?` sont des requêtes Rust sans binding Python (vérifié : aucun
`def *cycl*/*gap*`, ni Tarjan, dans `gcn-python/reasoning` ni `verbalizer` —
seul un helper d'affichage `_gap_value`). `PROVENANCE?` n'existe même pas côté
Rust (constaté : SAD + `query.rs` muets — la provenance se lit dans les CIR
et les enveloppes SA, pas en requête). Restent : `CYCLES?`, `GAPS?`,
`RELIABILITY <label>?`, tous prouvés via `gcn query --ir F <requête>` sur IR
forme Python-émetteur (réponses `cycle_list`, `gap_list`,
`reliability_report`, JSON validé).

## Décision

Chemin retenu : **CLI Rust en sous-processus, stateless** (`engine_bridge/rust.py` :
`interroger()` générique + `interroger_chaine()`, timeout directive, JSON
validé, IR éphémère nettoyée, fail-closed `RustIndisponible`). Coût : ~ms +
une écriture IR par requête (bornée par les plafonds T3.4). Amende I1 : la
liste blanche couvre les IMPORTS ; le subprocess isolé (timeout + schéma
validé, seul module `engine_bridge` à spawner `gcn`, garde par test) est
autorisé — même régime que T5.4 l'exigeait, étendu de CHAIN (ADR-0012) aux
3 requêtes. `trouver_binaire()` partagé (`GCN_BIN`/PATH/défaut dev).

## Conséquences

T5.5 construit `query_cycles`/`query_gaps` (+ `counterfactual`, voie Python
`reason` existante — pas de CLI requis) sur `interroger()`. Entrée T5.5 :
`temporal_gap` doit flotter (moteur → IR : `CirCore` ne le porte pas —
conception à trancher en T5.5, pas ici).

## Alternative rejetée

Binding Python : inexistant (pas de portage — ADR-10). Réimplémenter
Tarjan/gaps côté SA : interdit (même famille qu'ADR-10).
