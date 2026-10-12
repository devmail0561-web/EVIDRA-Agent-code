# Evidra (SA) — Journal d'implémentation (T0 → T3.6)

> Exhaustif, détaillé, concis. État au 2026-10-12, commit `1b02592` (+ T3.8 ci-dessous, à commiter).
> Source de conception : `ETUDE_SA.md` (30 sections). Plan : `PLAN_SA.md` (+ patchs P1–P7 appliqués).
> Dépôt : `devmail0561-web/EVIDRA-Agent-code`, branche `main`. Moteur : `gcn-python 4.0.0` @ `20163da` (branche refacto non mergée, cf. `engine-compat.md`).

## 1. État d'avancement

| Phase | Jalon | Tâches | Statut |
|---|---|---|---|
| 0 — Scaffolding | J0 ✅ | T0.1–T0.7 | Vert (CI équivalent local) |
| 1 — Noyau harness | J1 ✅ | T1.1–T1.7 | Vert : 498/500 SLOC, mypy strict, 0 dépendance noyau→mémoire/outils/moteur |
| 2 — Mémoire | J2 ✅ | T2.1–T2.8 | Vert : crash sans perte, compaction éprouvée, index≡scan, SLO mesurés |
| 3 — Pont moteur | J3 ⏳ | T3.1–T3.8 ✅, T3.9 ❌ | Reste : tranche verticale gold-219 |
| 4–10 | — | — | Non commencées |

Gate permanent (chaque tâche) : `ruff check` + `ruff format --check` + `mypy` (kernel, memory) + `pytest` (+ `--disable-socket`) + `lint-imports` + SLOC < 500. Compteur : **186 tests**, tous verts.

## 2. Architecture réelle

```
src/evidra/
  kernel/        498 SLOC — contrats, manifeste, registre, gate, scheduler (stdlib, <500, I2)
  memory/       1066 SLOC — wal, snapshot, envelope, index, store, memoire, registres, sous_graphe
  engine_bridge/ 390 SLOC — moteur.py, travailleur.py, extract.py, provenance.py, graphe.py,
                            reason.py, validate.py (SEUL importateur `gcn`, I1)
  tools/         135 SLOC — ingest.py (entry-point `evidra_tools:ingest` déclaré + chargeable)
  logging.py             — JSON + hiérarchie EvidraError (hors noyau)
  adapters|api|boot|directive|monitor|output|security/ — vides (`__init__`), phases 4–9
```

Dépendances : `kernel` ← `memory`, `tools`, `engine_bridge` (jamais l'inverse) ; `engine_bridge` → `memory` (enveloppes) + `gcn_python` ; `tools/ingest` → `kernel` + `memory`. Vérifié par `lint-imports` (contrat KEPT) + grep.

## 3. Phase 0 — Scaffolding et garde-fous (J0)

- **T0.1** — `pyproject.toml` (`evidra`, ≥3.11, `uv`, dep `path` éditable `../projet_CNM/gcn-python`), layout `src/`, `README.md`, `.gitignore`, `uv.lock` versionné. Acceptation adaptée : `uv sync --frozen && uv run pytest` verts (`import evidra` OK). Écart : `uv sync` initial bloqué hors-ligne (cache vide) → venv pip transitoire, résolu (cache peuplé, chemin canonique `uv` rétabli).
- **T0.2** — Surface moteur résolue (`docs/engine-compat.md`) : `GCNEngine`+`analyze/analyze_batch` (`gcn_python.engine`), `reason/reason_question/verify_path` (`reasoning.engine`), `CausalGraph` (classe `verbalizer.instructions` + Protocol `layer3.interface`). `layer0.engine_b.analyze` EXCLU (segmentation, pas des CIR). Smoke test FR+EN (pipeline minimal sans checkpoint ni `gcn-cli`) : CIR + provenance 5 clés, dédup M1b. Constats : install système `gcn_python` 2.5.0 masquée par sys.path → résolu par install éditable 4.0.0 ; `gcn-cli` absent (NO-GCN-BIN → parseurs stubs, T5.4 reste à trancher) ; gold-219 = somme des classes d'`accuracy_gold219.json`, fichier source des 219 phrases non localisé (risque T3.9).
- **T0.3** — `ruff` (lint+format) et `mypy --strict` (kernel, memory) verts. `mypy` absent du poste → installé dans l'env.
- **T0.4** — Garde I1 : `.importlinter` (seul `engine_bridge` importe `gcn`, KEPT) + `test_engine_boundary.py` (AST : symboles hors liste blanche interdits hors bridge, canari inclus).
- **T0.5** — Garde I2 : `scripts/sloc.py` (lignes de code hors commentaires/docstrings, déterministe) + `test_kernel_budget.py` (<500 SLOC, aucun nom concret de plugin dans le code — commentaires/docstrings exclus, corps de l'enum `Verb` exclu car vocabulaire de permissions §13.3, pas noms de plugins).
- **T0.6** — `ci.yml` (3.11/3.12 : ruff, mypy, lint-imports, pytest+cov ; clone moteur au SHA pinné), `offline.yml` (`--disable-socket`, vert), `bench.yml` (manuel, run bench réel depuis T2.8).
- **T0.7** — `docs/adr/modele.md` + ADR-0001–0010 (dépôt séparé, WAL dédié, single-writer, noyau stdlib, entry-points, règles pas LLM, partition jour 1, tiède pas chaud, HMAC mono-opérateur, `query_chain` coquille). ADR-0010 porte le point ouvert `GCNEngine` (classe hors liste blanche mais seul point de construction — à trancher avant T3.1 effectif, garde stricte en attendant).
- **Renommage** : Hermès → Evidra partout (package, entry-points `evidra_*`, CLI, erreurs) ; §5.1 de l'étude garde la mythologie d'Hermès sous le nom Evidra (résidu search-replace signalé à l'auteur, impact code nul).

## 4. Phase 1 — Noyau du harness (J1)

- **T1.1** — `kernel/contracts.py` (82 SLOC) : `Status` (ok/degrade/refused/failed), `Verb` (6), `Cost`/`CostHint`, `ToolResult` (total, `trace_ref`), `RawDoc` (uri/texte/channel/mime/**published_at**/**cites** — §6.9/§8.5 anticipés), `Cursor` (NewType), `Record`, `Store`/`Tool`/`Adapter` (Protocols runtime-checkables), `Context{store, domain, tick}`, `HARNESS_VERSION="1.0"`. Suite de contrat : conforme accepté, champ manquant / `side_effects` typé `str` rejetés.
- **T1.2** — `kernel/manifest.py` : `Manifest`/`Permission` frozen, semver stricte, `harness_required` parsé (`parse_version`, comparé en T1.3), verbes validés, fail-closed motivé (`ManifestError`), sans Pydantic (ADR-0004). 20 cas.
- **T1.3** — `kernel/registry.py` : découverte entry-points (groupes `evidra_*`, injectable en test), cycle `discovered→validated→enabled→running→disabled|quarantined`, 3 échecs ⇒ quarantaine auto, `harness` trop récent ⇒ `disabled` motivé, rapport (nom, état, motif). Méthode nommée `approve` (pas `validate`) pour éviter la collision I2 avec l'outil `validate` cité au plan. 7 cas.
- **T1.4** — `kernel/gate.py` : `can(politique, outil, verbe, scope, *, motif)` → `Decision` (jamais levée) ; défaut tout-interdit-sauf-`read` ; `forbidden` > `allowed` ; `delete` exige motif WAL ; correspondance exacte/`*` (jamais d'élargissement) ; `refuse()` → reçu `REFUSED` traçable. Suite adversariale (9 cas : défaut, verbe inconnu, scope vide, élargissement, priorité, delete, traçabilité).
- **T1.5** — `kernel/scheduler.py` : mono-thread, P1–P6 strictes, une action/niveau/tick, file `Queue` + `Future` (réveil immédiat), budgets (`max_tool_calls`, `max_ingest_per_cycle`, `max_cycle_ms`, `max_wal_bytes`, `reserve_fond`) tracés `budget:`, anti-famine prouvée (fond garanti sous chauffe haute), effet qui lève ⇒ reçu `FAILED` sans crasher, `boucler(Event)` arrêt propre, no-op < 10 ms. Compression (enums fonctionnelles, tuples internes, messages `_ko`) pour tenir I2.
- **T1.6** — `evidra/logging.py` (hors noyau) : `JsonFormatter`, `configurer()`, `log_recu()` (tick/outil/status/coût), hiérarchie `EvidraError` (noms T1.6, `noqa N818` justifiés). `ManifestError`/`RegistryError` restent `ValueError` (antérieurs, unification différée sans impacter I2).
- **T1.7** — `test_architecture.py` : tick complet outil+adaptateur factices sans toucher au noyau + gel du jeu de modules kernel.
- **J1** : 498/500 SLOC, mypy strict vert, contrats verts, 0 dépendance noyau→mémoire/outils/moteur (lint-imports + grep : seules des docstrings mentionnent `memory`).

## 5. Phase 2 — Mémoire de connaissance (J2)

- **T2.1** — `memory/wal.py` : un stream = `wal.jsonl`, `seq` croissant (reprise au max + `seq_depart` pour continuité post-troncation), CRC32 sur JSON canonique, fsync par batch (seuils provisoires configurables), fsync dossier à la création, `filelock` (2e instance refusée, `verrouiller=False` pour les flux d'un magasin), `relire(depuis=)` tolérant (ignorés/crc/trous/tronquée/doublons ; lignes pré-snapshot pliées, ni valides ni ignorées). Preuves : propriété hypothesis (rejeu ≡ état, 40 ex.), `kill -9` mi-batch (0 perte fsyncée, `tests/fault/`).
- **T2.2** — `memory/snapshot.py` : `{version, last_seq, state}`, tmp→fsync→prev→rename→fsync dossier ; `charger` (snapshot/prev/vide + rejeu `seq>last_seq`, version inconnue ⇒ repli signalé) ; `compacter` (seuil octets, hooks `PanneSimulee` tmp/prev/rename/troncation — état rechargé identique aux 4 étapes) ; tombstones rejoués sans snapshot forcé. Limite honnête documentée : snapshot corrompu + WAL tronqué ⇒ l'intervalle prev→snapshot est perdu (cas écriture déchirée, lui, récupère complet).
- **T2.3** — `memory/envelope.py` : `CirCore`/`Provenance` frozen (+`explicit`/`negated` constatés moteur, +`content_sha256`/`published_at` patch P4), `Envelope` mutable à `cir` lecture seule (property, `AttributeError` sinon), `Statut` (7), `Derivation`, spans `Token/ Code/Synthetic` (+ formes dict moteur, source unique ici), `cle_observation` (sans volatiles) vs `cle_triplet` (D, src, rel, dst normalisés), `normaliser_label` unique (casse/accents/espaces), `fabriquer_derivee` (2 justifications distinctes), `confirmer` (derived refuse — **I6**), `resume()` / `enveloppe_depuis_resume()` aller-retour lossless.
- **T2.4** — `memory/store.py` (`Magasin`, Protocol `Store`) : clés `domains/<d>[/<sous>]` + `registry/<nom>` via `sous_dossier` (évasion refusée), création à la demande, **verrou unique racine** (les WAL par flux se verrouillaient mutuellement — corrigé), `lookup` WAL puis cache snapshot (`tombstone` masque, `op="snapshot"` pour le replié), `snapshot`/`recharger` par rebuild (`appliquer` requis, **défaut `appliquer_domaine`** sur `domains/*`), compteurs d'accès (isolation A/B prouvée). 2 bugs corrigés en cours (verrou, lookup aveugle) + chargement paresseux.
- **T2.5** — `memory/index.py` : `depuis/vers/tokens/relations/tiers` (seuils 0.85/0.65 **provisoires**, directive en T4.1), ajout O(1), retrait propre, `reconstruire`, `causes/effets` (exact normalisé, repli tokens), `sortants/entrants/bouts` exacts (BFS T3.4). Preuves : propriétés hypothesis (index≡scan, tombstones) ; SLO mesuré p99 < 50 ms sur 100k (en fait ~0.01 ms).
- **T2.6** — `memory/registres.py` : 4 streams (`sources`, `aliases`, `models`, `tasks`), upsert générique, tâches `pending/running/done/abandoned` (expiration à horloge injectée, motif exigé, jamais supprimées), curseurs `op cursor` (jamais à côté des sources), modèles consignés sans consommation (gate B2).
- **T2.7** — `LoadReport` par stream (snapshot/replayed/skipped/crc/gaps/ms + `en_dict`), attaché au `Chargement`, consommé en T4.5.
- **T2.8** — `tests/bench/synthetique.py` (10k/100k/500k), `test_slo_p1.py` (insertion/chargement/p99/rejeu), `scripts/mesurer_slo.py` → `benchmarks/slo-p1-2026-10-11.json` : insertion **110k arêtes/s**, 200 requêtes ~1 ms, **p99 0.011 ms**, rejeu WAL **71k lignes/s**. `bench.yml` passé en run réel.
- **ADR-0011** (ajouté en T2.2) : data_dir toujours explicite (`--data-dir` requis, pas de défaut), tout état SA sous data_dir via `sous_dossier()`, sources lecture seule, sorties dans data_dir.
- **J2** : les 4 critères du plan sont verts.

## 6. Phase 3 — Pont moteur (en cours, T3.1–T3.6 ✅)

- **T3.1** — `engine_bridge/` : `Moteur` (Protocol injecté, moteur jamais importé), `travailleur.lancer()` (worker + timeout directive, patch P3), `extract.extraire()` (logique nulle : OK/DEGRADE/FAILED, `ignores` comptés, deepcopy entrée+sortie, jamais levée). Tests stub + intégration vrai moteur (contrat + provenance).
- **T3.2** — `provenance.py` : `envelopper()` (ref si `None`, span adaptateur autoritaire, `content_sha256` toujours, copie profonde, jamais d'invention ; ref Rust existante préservée), `verifier()` (re-hash, I4), `vers_noyaux()` (dict → `CirCore` sans perte, ref exigée). 11 cas dont I4 bout-en-bout.
- **T3.3** — `graphe.py` : `cir_pour_moteur()` (noyau seul, ids = labels normalisés), `ajouter`/`materialiser` via `add_cir` public origine `document`. **Constat** : poids document = 1.0 → sans distorsion ; copies d'attrs par le moteur. Acceptation : incrémental ≡ rebuild (`empreinte` sur `.edges` public, jamais le cache d'inférence).
- **T3.4** — `sous_graphe.decouper()` : BFS exact (pas de repli lexical), profondeur 2, plafonds **500/2000 = MAX_NODES/MAX_EDGES constatés**, coupe arête-complète (un nœud coupé fait sauter son arête — sinon le matérialisé dépasse quand même), `tronque` explicite. Acceptation : 100k arêtes → moteur ≤ plafonds.
- **T3.5** — `reason.py`/`validate.py` : `raisonner_chaine` (budget en argument, worker, OK/DEGRADE/FAILED, preuves vérifiées + confiance min, profondeur via T3.4 / top-k TOPK=5 interne documentés) ; `verifier_lien` (`reason` + `verify_path` public, `min_conf` transmise, pas de preuve = DEGRADE jamais FAILED). `derived` marqués `ingestible: False` + test contrat miroir T3.6 (zéro ingéré). Constats : statuts `ok`/`degrade` moteur.
- **T3.6** — `memory/memoire.py` (`Memoire` par domaine : une entité par triplet — première observation gardée —, `vues`, index ; `observer()` nouvelle/confirmation/idempotente via `confirmer`, alias passe-plat, `appliquer_domaine` strict + rebuild tolérant) ; `tools/ingest.py` (`OutilIngest` Tool+manifeste, porte `can()` → `refused` sans effet, seuils directive, drops par motif → DEGRADE, `trace_ref` seq WAL, entry-point déclaré et chargeable). Règles tranchées : entité count=1 à la création, même clé → idempotent (sans WAL), même triplet autre clé → confirmation, drops au reçu seul (cohérent T1.4), `seq_depart` possédé par le Store. Décisions reportées : mapping `min_extraction_method`→ensemble en T4.1, fiabilité T6.3 (0.5 neutre ici).
- Reste J3 : **T3.7** (`local_files` : mtime+hash, curseur, Token/CodeSpan, lecture seule ADR-0011), **T3.8** (dogfood `code` offline + job), **T3.9** (tranche verticale gold-219, 5 nombres — fichier source des 219 phrases à localiser).

## 7. Invariants I1–I12 : état d'application

| # | Invariant | Mécanisme | État |
|---|---|---|---|
| I1 | Seul `engine_bridge` importe `gcn` (+ liste blanche) | `.importlinter` KEPT + test AST + canari | ✅ vert |
| I2 | Noyau < 500 SLOC, sans noms concrets | `sloc.py` + `test_kernel_budget` (498/500 ; `Verb` exclu : vocabulaire, pas plugins ; `approve` pas `validate`) | ✅ vert, marge 2 |
| I3 | Écriture unique : `ingest()` (+ maintenance) | `OutilIngest` seul écrivain graphe (T6 maintenance à venir) | ✅ structurel |
| I4 | Pas de sortie sans provenance | `verifier()` + tests (ref/span/hash) | ✅ vert |
| I5 | `UNCONFIRMED` ≠ `FAUX` | Énumération fermée (T5.3, non commencé) | ⏳ gate T5.3 |
| I6 | `derived` ne confirme jamais, jamais ré-ingéré | `confirmer` + test dédié + `ingestible: False` + contrat T3.5 | ✅ vert |
| I7 | Moteur ne voit ni enveloppe ni contexte | `cir_pour_moteur` (noyau seul), `empreinte` sur `.edges` public | ✅ (interprétation documentée T3.3) |
| I8 | Tout-interdit-sauf-`read`, `delete`+motif | `can()` + suite adversariale | ✅ vert |
| I9 | `provisoire` jamais en constante | Seuils WAL/index configurables + marqués ; lint dédié **non écrit** | ⚠️ partiel (lint en T4.1+) |
| I10 | Noyau offline | `pytest --disable-socket` (job + local, verts) | ✅ vert |
| I11 | Ingéré = donnée citée, jamais instruction | Corpus adversarial (T9.7, non commencé) | ⏳ gate T9 |
| I12 | Fail-closed, WAL tolérant par ligne | `relire` (skip+compteurs), rebuilds tolérants, `test_architecture` | ✅ vert |

## 8. Patchs P1–P7 : état

P1 (reçus : mutation seule, no-op zéro écriture) ✅ appliqué au plan (à faire respecter en T4.4) · P2 (T3.9 tranche verticale) ✅ planifié, non exécuté (bloqué : fichier gold-219) · P3 (worker+timeout) ✅ appliqué (travailleur, scheduler, coquilles) · P4 (published_at/hash/label-brut) ✅ appliqué (enveloppe, provenance, alias passe-plat) · P5 (nonce/ts, clés, directive signée, rétention §17.6, anti-ReDoS, lignage) ⏳ phases 7–9 · P6 (table opposition §5, déclencheur UNCONFIRMED, étiquetage counterfactual) ⏳ T5.3/T5.5 · P7 (noisy-OR, premier-rapporteur) ⏳ phase 10 (B3).

## 9. Constats moteur (vérifiés, pas supposés)

`document` poids 1.0 (matérialisation neutre) · `add_cir` exige origine + valide 19 relations (`cause`, pas `causes`) + normalise ids en str · `reason()` pur/borné/budgeté, degrade `oversize` > 500 nœuds/2000 arêtes, TOPK=5 interne · `verify_path` : maillon présent, non-`negated`, causal, seuils, opposées (§9.4) · `analyze_batch` dédup M1b + copies · provenance Python `ref=None`, span marqueur/`"synthetic"` · `layer0.engine_b.analyze` = segmentation (hors liste blanche) · branches non mergées (refacto +109/master, pin SHA, risque rebase documenté) · `gcn-cli` absent.

## 10. Points ouverts et risques

1. **Marge I2 : 2 SLOC** (498/500) — plus aucune ligne kernel sans compensation ; le noyau est complet (T1.7), aucune croissance prévue.
2. **Classe `GCNEngine` hors liste blanche I1** — garde stricte, arbitrage ADR-0010 avant usage effectif en T4.5.
3. **Gold-219 introuvable en un fichier** (85 dans `gold_mini`, 219 = somme classes) — bloque T3.9 ; à clarifier côté moteur/dataset.
4. **`uv sync` initial fragile hors-ligne** (cache vide) — résolu ici, à surveiller en CI.
5. **Lint I9 non écrit** — seuils provisoires repérés (`PROVISOIRE`, seuils WAL/index) mais sans garde auto avant T4.1.
6. **Décisions reportées** : mapping `min_extraction_method` (T4.1), fiabilité sources (T6.3), règle d'opposition détaillée (T5.3), accès CYCLES/GAPS (T5.4 : binding vs CLI), `pending` conversation (phase 10).

## 11. Métriques et gate

186 tests (20 manifest, 15 store, 14 snapshot, 11 scheduler, 11 provenance, 10 envelope, 9 gate-adversarial, 8 registres, 8 ingest, 7 sous-graphe, 7 registry, 7 extract, 6 wal, 6 contrats, 5 reason, 5 memoire, 4 validate-lien, 4 graphe-domaine, 3 travailleur/logging/index/reason-moteur/slo, 2 rapport/budget/boundary/architecture/smoke, 1 scaffolding/extract-moteur/index-bench/wal-crash) + propriétés hypothesis (WAL, index) + fautes (`kill -9`, 4 étapes compaction). SLOC : kernel 498, memory 1066, engine_bridge 390, tools 135 (total 2160). SLO mesurés : §6 + `benchmarks/slo-p1-2026-10-11.json`. Offline vert. 18 commits, tous poussés (`origin/main` synchro).

## 12. Journal des commits

`3c8e00a` J0+T1.1 · `ee95532` T1.2 · `968f03e` T1.3 · `7b676a6` T1.4 · `ad11321` T1.5 · `4e6d90f` T1.6+T1.7 (J1) · `a18bef8` T2.1 · `199c9c9` T2.2+ADR-0011 · `f927ab5` T2.3 · `28cab04` T2.4 · `f1202a5` T2.5 · `6f5ad9f` T2.6 · `905d9d4` T2.7+T2.8 (J2) · `5b99c6d` T3.1 · `44ade14` T3.2 · `520d816` T3.3+T3.4 · `b958ca0` T3.5 · `0198cd2` T3.6 · `96af26e` docs T0→T3.6 · `1b02592` T3.7.

## 13. T3.7–T3.8 (au-delà du journal T0→T3.6)

- **T3.7** (`1b02592`) : `adapters/local_files.py` — poll mtime+hash+sha, globs stdlib, curseur JSON opaque (poll tolérant, ack strict), lecture STRICTEMENT seule (aucun sidecar, `.git`/caches exclus, binaire sauté), `etendue()` TokenSpan couvrant / CodeSpan fichier (grossier mais vrai ; fin au mot = T5.4), `RawDoc` réels offline. Manifest : `permissions` vides autorisées (absent refusé). Entry-point déclaré et chargeable.
- **T3.8** (ce commit) : `directives/code.dogfood.json` (domaine `code`, seuils 0.0/ml_python justifiés B1) ; `engine_bridge/binaire.py` (résolution `GCN_BIN`/PATH/défaut dev) ; `ingestion.py` (F1 partagé : phrases → extract → ancre document → enveloppe → vérifie → ingest, absorbé en T4.4) ; `tests/offline/test_dogfood.py` (corpus fixture, lattice réelle si `gcn` présent sinon stub, I4 vérifié, offline) ; `scripts/dogfood_code.py` (run dépôt réel). **Constat décisif** : CLI `gcn` 4.0.0 présent et fonctionnel → lattice réelle + poids d'essai (structure réelle, poids bruts, B2 intact : aucun checkpoint touché). Mesure dogfood : 53 docs, 7900 phrases/CIRs, 234 entités, 185 confirmations, 6965 idempotentes (poids bruts → triplets génériques répétés, dédup conforme), 0 dropped/invalide, réponses avec `file://` citées. Labels `hidden_cause(?)` : encodeur d'essai, pas une qualité (B1, T3.9 mesure).
