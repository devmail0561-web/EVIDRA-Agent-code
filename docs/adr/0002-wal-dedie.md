# ADR-0002 — WAL SA dédié (SessionStore non réutilisé)

- Date : 2026-10-11
- Statut : accepté
- Fonde : ETUDE_SA.md §14 / PLAN_SA.md §3.4 (phase 2)

## Contexte

Constaté : `SessionStore` = photo atomique sans fsync, journal append sans
fsync ni lock, écrit au `save()` seulement, sans seq/checksum, suppressions
non rejouables, dédup incluant des volatiles.

## Décision

WAL SA séparé : fsync par batch, `seq` par ligne, CRC, tombstones rejouables,
snapshot versionné + `.prev`, compaction sur taille en octets, clé de dédup
sans champs volatils, rejeu tolérant par ligne.

## Conséquences

Phase 2 prouve : 0 perte après `kill -9` des lignes fsyncées, compaction
atomique, `ack()` après fsync, file morte après 3 échecs.

## Alternative rejetée

Réutiliser `SessionStore` — perte entre mutation et `save()`, corruption
prouvée en cas de crash.
