# ADR-0011 — Racine data_dir explicite et confinement des fichiers SA

- Date : 2026-10-11
- Statut : accepté
- Fonde : demande d'encadrement des répertoires (contexte : T2.2) / ETUDE_SA.md §6, §9, §13 / PLAN_SA.md §6.4

## Contexte

L'agent crée des fichiers d'état (WAL, snapshots, registres, reçus) ET lit des
dossiers sources (ex. `local_files` sur un dépôt) ET produit des sorties
(rapports). Sans règle stricte, l'état SA fuirait dans les dossiers sources
(sidecars, curseurs, snapshots) et les sorties pollueraient le projet
surveillé — exactement ce que la séparation SA/moteur interdit côté code.

## Décision

1. **Pas de workspace implicite** : la racine des données (`data_dir`) est
   toujours explicite (`--data-dir` requis au CLI, T4.6 ; fail-closed sinon).
   Jamais de défaut vers le répertoire courant.
2. **Tout fichier d'état SA vit sous `data_dir`** (`domains/<d>/`,
   `registry/...`, cf. §6.4 du plan), construit uniquement via
   `sous_dossier()` qui refuse `..`, segments vides, séparateurs et absolus.
3. **Sources en lecture seule** : aucun fichier SA à côté des documents
   ingérés (curseurs persistés dans `data_dir` via les tâches, §13.4) ;
   l'adaptateur `local_files` (T3.7) ne fait que lire.
4. **Sorties produites** (rapports, T5.8) : dans `data_dir`, ou cible
   explicite de la directive — jamais dans les dossiers sources.

## Conséquences

`memory/snapshot.sous_dossier()` + tests de confinement (rien hors du
dossier de stream) ; Store (T2.4) seul constructeur de chemins ; CLI sans
`--data-dir` = refus.

## Alternative rejetée

Défaut `~/.evidra` ou `./.evidra` implicite — état caché, mélange des
contextes, debug pénible.
