# ADR-0014 — Frontière `memory/` : types partout, état injecté, écritures via `ctx.store`

- Date : 2026-10-13
- Statut : accepté
- Fonde : PLAN_SA.md §5 (règle « `tools/` et `adapters/` n'importent jamais `memory/` ») / point reporté post-J4, tranché ici

## Contexte

Le plan §5 interdit aux outils et adaptateurs tout import de `memory/`
(accès via `ctx.store`, filtré par `can()`). Constat au code (vérifié par
`grep`, figé par `tests/unit/test_frontiere_adapters.py`) :
- 9/9 outils importent `memory.memoire` (`Memoire`, `id_triplet`, `Triplet`)
  mais reçoivent les instances par injection (`OutilX(memoires, ...)` depuis
  `demarrage`/`pont`, jamais de global) et n'importent ni `memory.store` ni
  `Magasin` — la seule écriture passe par `ctx.store.append` (`OutilIngest`) ;
- les 3 adaptateurs importent `memory.envelope` uniquement (`Span`/`CirCore` :
  l'ancrage de provenance T3.2 et la validation T9.3 EXIGENT de construire ces
  types — sans eux, aucun `RawDoc` ne porterait de `ref`/`span` réel),
  jamais `store`/`memoire`/`Magasin`, jamais d'écriture (absents de la garde I3).

L'intention du plan — aucun écrivain sauvage, mutation permissionnée et
tracée — est tenue par I3 + `can()` + I8. Faire transiter les *lectures* par
`ctx.store.lookup` n'ajouterait aucune sécurité (I8 : `read` par défaut) et
coûterait une indirection sur chaque requête (les SLO p99 T10.5 tiennent
parce que les lectures sont mémoire-directe : 0.026/0.23 ms).

## Décision

Amende §5, en trois niveaux exécutés par `test_frontiere_adapters.py` :
1. **`memory.envelope` autorisé partout** (types purs, sans état) ;
2. **`memory.memoire` réservé aux outils**, en lecture sur instances injectées
   (jamais de construction globale, jamais de `Store` direct) ;
3. **écritures par `ctx.store.append` uniquement** (`OutilIngest`, I3
   inchangé) ; adaptateurs : ni `store`, ni `memoire`, ni `Magasin`, ni écriture.

## Conséquences

`test_ecrivains.py` (I3) + `test_frontiere_adapters.py` (cette ADR) sont les
gardes exécutables. `memoire.py` n'importe aucun adaptateur (sens unique :
`CANAUX_AGENTS` nommé, pas d'import). Phases 10 : inchangées.

## Alternative rejetée

Refactor complet vers `ctx.store` pour les lectures : 9 outils + tests
réécrits, SLO p99 à re-mesurer, zéro gain de sécurité (I3+I8 couvrent déjà).
Interdire `envelope` aux adaptateurs : impossible sans tuer l'ancrage T3.2
(ils ne pourraient plus construire ni span ni CIR).
