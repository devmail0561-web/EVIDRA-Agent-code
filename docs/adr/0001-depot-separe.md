# ADR-0001 — Dépôt séparé, moteur en dépendance path éditable pinnée

- Date : 2026-10-11
- Statut : accepté
- Fonde : ETUDE_SA.md §1 + §12bis / PLAN_SA.md §3.4 (T0.1, T0.2)

## Contexte

La séparation SA/moteur est structurelle et non négociable : toute capacité
d'orchestration, persistance ou communication appartient au SA, jamais à
`gcn-core`/`gcn-python`. Le SA doit pourtant consommer le moteur en dev
synchrone (pas de release moteur publiée pour l'instant).

## Décision

Dépôt, package (`evidra`) et `pyproject.toml` séparés du moteur.
Dépendance `gcn-python` en `path` éditable (`../projet_CNM/gcn-python`),
commit pinné en `docs/engine-compat.md` (actuellement `20163da` sur branche
refacto non mergée — risque documenté, ancre stable = première release).

## Conséquences

`uv sync --frozen` reproductible tant que le SHA existe ; CI clone le moteur
au SHA pinné ; `uv.lock` versionné.

## Alternative rejetée

Sous-package du moteur — violerait la séparation §1.
