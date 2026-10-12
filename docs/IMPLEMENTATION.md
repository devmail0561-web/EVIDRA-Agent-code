# Evidra (SA) — Journal d'implémentation (T0 → T4.7, J4 clos)

> Exhaustif, détaillé, concis. État au 2026-10-12 (J4 clos, voir §14).
> Source de conception : `ETUDE_SA.md` (30 sections). Plan : `PLAN_SA.md` (+ patchs P1–P7 appliqués).
> Dépôt : `devmail0561-web/EVIDRA-Agent-code`, branche `main`. Moteur : `gcn-python 4.0.0` @ `20163da` (branche refacto non mergée, cf. `engine-compat.md`).

## 1. État d'avancement

| Phase | Jalon | Tâches | Statut |
|---|---|---|---|
| 0 — Scaffolding | J0 ✅ | T0.1–T0.7 | Vert (CI équivalent local) |
| 1 — Noyau harness | J1 ✅ | T1.1–T1.7 | Vert : 498/500 SLOC, mypy strict, 0 dépendance noyau→mémoire/outils/moteur |
| 2 — Mémoire | J2 ✅ | T2.1–T2.8 | Vert : crash sans perte, compaction éprouvée, index≡scan, SLO mesurés |
| 3 — Pont moteur | J3 ✅ | T3.1–T3.9 | Clos : dogfood offline + 5 nombres écrits |
| 4 — Directives/boucle | J4 ✅ | T4.1–T4.7 | Clos : boucle gouvernée + CLI + arrêt propre |
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
- J3 clos : **T3.7** (`local_files`), **T3.8** (dogfood `code` offline + job), **T3.9** (tranche verticale, 5 nombres écrits — voir §13).

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

P1 (reçus : mutation seule, no-op zéro écriture) ✅ appliqué au plan (à faire respecter en T4.4) · P2 (T3.9 tranche verticale) ✅ exécuté (fixture + 5 nombres, voir §13) · P3 (worker+timeout) ✅ appliqué (travailleur, scheduler, coquilles) · P4 (published_at/hash/label-brut) ✅ appliqué (enveloppe, provenance, alias passe-plat) · P5 (nonce/ts, clés, directive signée, rétention §17.6, anti-ReDoS, lignage) ⏳ phases 7–9 · P6 (table opposition §5, déclencheur UNCONFIRMED, étiquetage counterfactual) ⏳ T5.3/T5.5 · P7 (noisy-OR, premier-rapporteur) ⏳ phase 10 (B3).

## 9. Constats moteur (vérifiés, pas supposés)

`document` poids 1.0 (matérialisation neutre) · `add_cir` exige origine + valide 19 relations (`cause`, pas `causes`) + normalise ids en str · `reason()` pur/borné/budgeté, degrade `oversize` > 500 nœuds/2000 arêtes, TOPK=5 interne · `verify_path` : maillon présent, non-`negated`, causal, seuils, opposées (§9.4) · `analyze_batch` dédup M1b + copies · provenance Python `ref=None`, span marqueur/`"synthetic"` · `layer0.engine_b.analyze` = segmentation (hors liste blanche) · branches non mergées (refacto +109/master, pin SHA, risque rebase documenté) · `gcn-cli` absent.

## 10. Points ouverts et risques

1. **Marge I2 : 2 SLOC** (498/500) — plus aucune ligne kernel sans compensation ; le noyau est complet (T1.7), aucune croissance prévue.
2. **Classe `GCNEngine` hors liste blanche I1** — garde stricte, arbitrage ADR-0010 avant usage effectif en T4.5.
3. **Gold-219 résolu** : `tranche_t2/t2_gold.json` (distribution exacte, FR/EN/ES, CIR gold) → fixture slim `benchmarks/gold-219.json` (69 Ko, traçable). Le gold ne fait pas partie du SA (fixture benchmark, comme T9.7).
4. **`uv sync` initial fragile hors-ligne** (cache vide) — résolu ici, à surveiller en CI.
5. **Lint I9 non écrit** — seuils provisoires repérés (`PROVISOIRE`, seuils WAL/index) mais sans garde auto avant T4.1.
6. **Décisions reportées** : mapping `min_extraction_method` (T4.1), fiabilité sources (T6.3), règle d'opposition détaillée (T5.3), accès CYCLES/GAPS (T5.4 : binding vs CLI), `pending` conversation (phase 10).

## 11. Métriques et gate

186 tests (20 manifest, 15 store, 14 snapshot, 11 scheduler, 11 provenance, 10 envelope, 9 gate-adversarial, 8 registres, 8 ingest, 7 sous-graphe, 7 registry, 7 extract, 6 wal, 6 contrats, 5 reason, 5 memoire, 4 validate-lien, 4 graphe-domaine, 3 travailleur/logging/index/reason-moteur/slo, 2 rapport/budget/boundary/architecture/smoke, 1 scaffolding/extract-moteur/index-bench/wal-crash) + propriétés hypothesis (WAL, index) + fautes (`kill -9`, 4 étapes compaction). SLOC : kernel 498, memory 1066, engine_bridge 390, tools 135 (total 2160). SLO mesurés : §6 + `benchmarks/slo-p1-2026-10-11.json`. Offline vert. 18 commits, tous poussés (`origin/main` synchro).

## 12. Journal des commits

`3c8e00a` J0+T1.1 · `ee95532` T1.2 · `968f03e` T1.3 · `7b676a6` T1.4 · `ad11321` T1.5 · `4e6d90f` T1.6+T1.7 (J1) · `a18bef8` T2.1 · `199c9c9` T2.2+ADR-0011 · `f927ab5` T2.3 · `28cab04` T2.4 · `f1202a5` T2.5 · `6f5ad9f` T2.6 · `905d9d4` T2.7+T2.8 (J2) · `5b99c6d` T3.1 · `44ade14` T3.2 · `520d816` T3.3+T3.4 · `b958ca0` T3.5 · `0198cd2` T3.6 · `96af26e` docs T0→T3.6 · `1b02592` T3.7.

## 13. T3.7–T3.9 (au-delà du journal T0→T3.6)

- **T3.7** (`1b02592`) : `adapters/local_files.py` — poll mtime+hash+sha, globs stdlib, curseur JSON opaque (poll tolérant, ack strict), lecture STRICTEMENT seule (aucun sidecar, `.git`/caches exclus, binaire sauté), `etendue()` TokenSpan couvrant / CodeSpan fichier (grossier mais vrai ; fin au mot = T5.4), `RawDoc` réels offline. Manifest : `permissions` vides autorisées (absent refusé). Entry-point déclaré et chargeable.
- **T3.8** (ce commit) : `directives/code.dogfood.json` (domaine `code`, seuils 0.0/ml_python justifiés B1) ; `engine_bridge/binaire.py` (résolution `GCN_BIN`/PATH/défaut dev) ; `ingestion.py` (F1 partagé : phrases → extract → ancre document → enveloppe → vérifie → ingest, absorbé en T4.4) ; `tests/offline/test_dogfood.py` (corpus fixture, lattice réelle si `gcn` présent sinon stub, I4 vérifié, offline) ; `scripts/dogfood_code.py` (run dépôt réel). **Constat décisif** : CLI `gcn` 4.0.0 présent et fonctionnel → lattice réelle + poids d'essai (structure réelle, poids bruts, B2 intact : aucun checkpoint touché). Mesure dogfood : 53 docs, 7900 phrases/CIRs, 234 entités, 185 confirmations, 6965 idempotentes (poids bruts → triplets génériques répétés, dédup conforme), 0 dropped/invalide, réponses avec `file://` citées. Labels `hidden_cause(?)` : encodeur d'essai, pas une qualité (B1, T3.9 mesure).

- **T3.9** : tranche verticale (`tests/bench/tranche.py` + `scripts/tranche_verticale.py` + subset test + `tests/essai.py` factorisé d_emb=16). Intégrité redéfinie (présence mémoire, pas raisonnement — les flags B1 faussaient la mesure). **5 nombres** (`benchmarks/tranche-verticale-2026-10-12.json`) : précision null (0 verdict positif), rappel 0.0 (plancher : labels annotateur vs surface + flags B1 ; recouvrement token ~40 % en diagnostic), spécificité 1.0, latences 7.3/10.3 ms, 256 docs/s, intégrité 1.0, ES 24 exclues (pas de lattice). Compteur : **195 tests**, noyau 498/500. J3 clos.

## 14. Phase 4 (J4) : directives, boucle, démarrage, CLI

- **T4.1** : `directive/schema.py` (Pydantic strict, `extra=forbid`) — §9.3 + budgets, permissions→`Policy`, staleness, provisoires `[provisoire]` (I9 : T_domaine/Nmax/quorum 2.0/révision 3.0), `delegate: Literal[disabled]` (gate P3), plafonds canaux, alias, agents pairs, regex validées ; `DirectiveError` précis ; `docs/contrats/directive.schema.json` + test anti-drift ; dogfood valide (commentaire JSON retiré — `extra=forbid`).
- **T4.2** : `directive/loader.py` (fail-closed) + `reload.py` (`Surveillant` : mtime+hash, ancienne conservée + alerte bornée, diff sources appliqué au registre sans restart, sha pour WAL). Hypothèse : noms d'adaptateurs uniques, clé `evidra_adapters:<nom>`.
- **T4.3** : `policy.py` hors noyau (TABLE §1.3, `Situation` gelée, `selectionner()` pure ; vide ⇒ aucun outil).
- **T4.4** : `boucle.py` hors noyau gelé (assignation `_budgets` documentée) — tick = tiède → tâches P4–P6 (COURS/TERMINÉE, panne→ABANDONNÉE) → sélection → tour → rapport ; `borner()` score+tronqué ; WAL : transitions, ingest, reçu `directive` (patch P1 : lus seuls sans mutation) ; `Magasin` verrou unique + cache snapshot + appliquer domaine par défaut. 8 cas (ordre P2<P4, budget tracé, anti-famine, tiède+hash, no-op zéro écriture).
- **T4.5** : `boot/demarrage.py` 5 phases (manifeste premier/divergent→degraded motivé, WAL inventorié, ABANDONED repris, modèles B2 + param_epoch noté I1 + préchauffage worker, mémoires rebuildées, boucle câblée) ; refus nets (verrou, directive) ; `version_moteur()` côté bridge (I1 intact) ; `Magasin.inventorier/synchroniser` ; crash `os._exit` → reprise identique prouvée.
- **T4.6** : `cli.py` (`run/ingest/query/compact/status`, `--data-dir` requis ADR-0011, `--essai` opt-in B1, ingest sans moteur → exit 2 ; query/status sans moteur ni verrou ; compact verrouillé-safe). `engine_bridge/essai.py` (fabrique partagée, `tests/essai.py` = shim).
- **T4.7** : tick boucle < 10 ms mesuré ; SIGTERM → reçu final + fsync + verrou libéré (subprocess, re-ouverture prouvée).
- Leçons : `set(str)` éclate (bug seuils) ; `poids` B1 faussent les nodiges (séparer intégrité/fidélité) ; d_emb=16 pas 4 ; permissions vides OK (absent refusé).
- Compteur : **236 tests**, noyau 498/500. J4 : boucle offline, crash sain, directive tiède.

## 15. Correctifs post-J4 (2026-10-12, audit sans complaisance)

Audit externe (suivi d'une vérification de fiabilité : l'audit initial annonçait ~20 `except`, 10 `print`, 186–236 tests — valeurs corrigées ci-dessous). Correctifs appliqués, tous vérifiés par la gate complète (`ruff check`, `ruff format --check`, `mypy`, `lint-imports`, `lint_provisoire.py`, `sloc.py`, `pytest` complet + `--disable-socket` offline) :

- **Noyau : setter `Budgets`.** `Scheduler.configurer_budgets()` ajouté ; `Boucle._tiede()` n'assigne plus `_budgets` en privé. Économie : alias dupliqué `_File`/`_Entree` fusionné. **499/500 SLOC**, mypy strict vert, `test_kernel_budget` + `test_architecture` verts.
- **`traiter_document` typé.** `adaptateur: SourceLocale` (Protocol `Adapter` + `etendue`/`canal`), `moteur: Moteur | None`, `outil: Tool`, `ctx: Context`. Correction d'audit : la porte `can()` n'était PAS court-circuitée (`OutilIngest.run` refuse via `can()`) — seul le typage `Any` était fautif.
- **CLI unifié sur `Magasin`.** `store.lire_domaine()` (snapshot + rejeu WAL + `memoire_depuis_etat`, sans verrou — utilisable agent tournant) + `store.inventorier_racine()` partagé par `Magasin.inventorier()`, `cmd_query` et `cmd_status`. `test_cli` + `test_store` verts (23 tests).
- **Imports `gcn` paresseux.** `reason.py`, `validate.py` (défauts `None` + import local, `FAILED "moteur non importable"` explicite), `graphe.py` (`CausalGraph` local à `materialiser`, annotations `Any`). Vérifié : `import evidra.engine_bridge.reason` réussit moteur absent.
- **Déduplication.** `util.borner()` (nouveau `evidra/util.py`, `boucle.borner` = alias re-exporté) → `tools/report` n'importe plus `boucle` ; `aretes_pour()` partagé (`_requetes_rust.py`) → `_aretes_requete` de `query_chain` supprimé ; `run()->_run()` des 8 outils → `util.garde()` (`counterfactual` garde son `avertissement` + log).
- **Stacks loggées.** `_LOG.exception` ajouté aux 8 outils (via `garde`), `counterfactual`, `boucle`, `ingestion`, `cli`, `demarrage` (directive, préchauffage, manifeste), `engine_bridge` (`extract/reason/validate`). Décision assumée : `kernel/scheduler.py` SANS logger (budget I2 — le reçu `FAILED` reste tracé via `log_recu`/WAL).
- **Garde I9 exécutable.** `scripts/lint_provisoire.py` (registre de 9 constantes : `version`/`constatee`/`spec`/`provisoire`) + `tests/unit/test_provisoire.py` + job CI. **9 constantes déclarées, 0 écart.**
- **I1 réparé (pré-existant).** `lint-imports` était `BROKEN` avant ces correctifs (`boot.demarrage → engine_bridge.moteur → gcn_python` transitif). `version_moteur()` déplacé dans `evidra/util.py` (métadonnées de distribution, aucun import `gcn`), re-exporté par `engine_bridge.moteur`. Contrat **KEPT**.
- **Hygiène.** `.gitignore` : ajout `.import_linter_cache/`, `.hypothesis/`.

Compteurs vérifiés : **291 tests** (`uv run pytest --collect-only` ; `pytest` système seul = 50 erreurs de collection, `uv run` exigé), noyau **499/500**, `lint-imports` KEPT. Non traité (reporté, inchangé) : `tools/ → memory/` direct (9/9 outils — invalide `PLAN_SA §5`, à trancher : appliquer `ctx.store` ou amender le plan), P1–P3 mortes, `output/`/`etat.py` non branchés, nommage FR/EN, pin moteur sur branche non mergée.

## 16. Réfutation de l'audit n°2 + correctifs (2026-10-12)

Second audit (invariants + adverse) réfuté point par point, preuves au code ; les concessions + durcissements légitimes sont corrigés ci-dessous. Gate complète verte : `ruff`, `mypy`, `sloc` **499/500**, `lint_provisoire` **7 constantes, 0 écart**, `lint-imports` KEPT, **317 tests** (+26), offline vert.

Réfutations retenues (l'audit n°2 surévaluait) :
- `Future` skippé : aucun `.result()` en attente dans `src/` (`boucle.py:187` jette le retour) — pas d'« attente infinie ». Corrigé quand même : les `Future` skippés sont désormais résolus en `DEGRADE "budget dépassé"` (`scheduler.py`, +4/−4 lignes, I2 tenu) + test `test_evenement_skipe_par_budget_resout_degrade`.
- Course lecture/`compact` : jamais de corruption (rename atomique, `relire(depuis)` idempotent) — pire cas = lecture périmée sur chemin opérateur documenté « sans verrou ». `status` signale désormais les streams ignorés.
- FIFO : inatteignable (`is_file()` = réguliers seuls). Symlinks hors racine : trou réel, corrigé (`resolve()` + `is_relative_to`, boucle → `continue`, test `test_lien_hors_racine_ignore`).
- File non bornée : producteur unique (boucle, borné par les tâches), API vide — théorique, reporté à l'API.
- I3 « prétendu » : faux — `appliquer_domaine` ignore `receipt`/`drop` (aucun effet d'état), l'état du graphe n'a bien qu'un écrivain (`ingest`). Ajouté le mécanisme manquant : `tests/unit/test_ecrivains.py` (ensemble des 5 fichiers écrivains figé).
- I1 : `essai.py` hors liste blanche = scaffold dev opt-in documenté, pas chemin prod. Ajouté le mécanisme : `test_liste_blanche_dans_engine_bridge` (bridge hors `essai` = liste blanche stricte, jeu d'imports d'`essai.py` figé).
- `aretes_pour` trié : sans effet comportemental (`_assembler` joint par labels, ordre-indépendant) — test de déterminisme ajouté (ordre par id, pas par labels : correction d'un test d'abord écrit faux).

Correctifs appliqués :
- `relever_expiration` tolérant (`TypeError` + naive/aware + horloge illisible ⇒ `[]`, test dédié).
- `args_valides` supprimé (mort-né) ; `garde(..., journal=)` : les 8 outils loggent sous `evidra.tools.<nom>` (tests `caplog`).
- `SEUIL_HAUT/MOYEN` sortis du code : `quality.seuils_tiers` (`[provisoire]`, validé `0 ≤ m ≤ h ≤ 1`) devient source unique via `seuils_tiers_defaut()` ; `Index`/`Memoire`/`memoire_depuis_etat`/`lire_domaine` acceptent `seuils` (`None` ⇒ défaut schéma) ; `demarrage` câble la directive ; schéma JSON re-exporté ; registre I9 : 9 → 7 constantes.
- `cmd_status` tolérant (manifeste corrompu ⇒ `{}` + avertissement, exit 0 ; clé `invalides`) ; `_sceller_manifeste` fsync (fichier + dossier) ; `__all__` de `boucle.py` en fin de fichier ; maille I9 documentée + cas nominaux (orphelin/dérive/non-déclarée).
- Tests directs ajoutés (`test_correctifs.py`, 14 tests) : `garde` (passe-plat/panne/stack/logger), `version_moteur` (re-export/`unknown`), `aretes_pour`, `lire_domaine` (équivalence + inconnu), `raison=None` sans moteur, injection partielle `validate`, `SourceLocale`, `configurer_budgets`, identité `borner`.

Toujours reporté (inchangé, assumé) : `tools/ → memory/` direct, P1–P3 mortes, `output/`/`etat.py` non branchés, nommage FR/EN, pin moteur, file bornée (à l'API), corpus adversarial I11 (gate T9).

## 17. Phase 6 — cycle de vie (T6.1, J6 en cours)

- **T6.1** (`memory/lifecycle.py`, pur, 0 dépendance Store/horloge) : matrice `TRANSITIONS` des 7 statuts, `transition()` (motif exigé, illégale ⇒ `(False, rejet)` comptable), `promouvoir()` (ACTIVE dès 2 sources, CONFIRMÉE dès N directive, `derived` jamais — garde I6 redondante), `vieillir()` (STALE si non re-confirmée depuis T jours, dates illisibles ⇒ `None`, jamais levée).
- `Memoire` : `n_confirmee` (défaut canonique `Provisoire.n_confirmation` ajouté au schéma `[provisoire]`, défaut 3) câblé par `demarrage` ; promotion auto dans `observer()` (persistée via `add_edge`/`confirm` existants, sans nouvel op) ; `changer_statut()` (mutation + `update_status` par l'appelant) ; `appliquer_domaine` rejoue `update_status` (réécriture capsule complète).
- Tests `test_lifecycle.py` (7) : matrice exhaustive 7×7, motif vide, seuils, I6 dérivée, stale (naive/aware ⇒ `None`), roundtrip WAL, promotion ingest. Compteur : **324 tests**, noyau 499/500, gardes vertes.

- **T6.2** (`lifecycle.py` : `fraicheur`, `confiance_effective`, `recenser_stales`, purs) : `exp(-(now−t)/T_domaine)` sur `published_at` source (jamais ingestion) ; inconnu ⇒ `(1.0, False)` ; futur ⇒ plafonné 1.0 ; effective = CIR × fraîcheur, CIR intact. `evidra maintenance` (lecture seule, `--directive` optionnelle, `--maintenant` injectable) liste les candidats P5 avec confiance effective. Création de tâches P5 reportée au consommateur `maintenance` (T6.4) — pas de tâches pendantes sans consommateur.
- Tests (5) : décroissance (`e^-1` à T), horloges 7/90/365 j, CIR intact, recensement, CLI `maintenance` (`ACTIVE` listée à +60 j). Compteur : **329 tests**, gardes vertes.

- **T6.3** (`memory/sources.py`, pur) : `Compteurs` + `taux_*` + `fiabilite` (formule spec `[provisoire]`, 6 seuils ajoutés à `Provisoire` avec validateurs, garde anti-drift `SeuilsSources == Provisoire` en test) + `bilan` (`blocked` stocké prioritaire, amorçage `monitored`) + `signale` (basculement vers `suspect`, consommable phase 7). `Registres` : `noter_compteurs`/`compteurs` typés. `OutilIngest` alimente contributions + confirmations indépendantes par `ref` (lecture-modification-écriture best-effort loggée, `op contrib`). L'alimentation `contradicted_*` relève de l'arbitrage (T6.4, attribution des refs) — `signale()` testé sur compteurs synthétiques.
- Tests `test_sources.py` (7) : formule exacte, plancher/amorçage/`blocked`, tolérance, signal, drift schéma, alimentation ingest, registres typés. Compteur : **336 tests**, noyau 499/500, gardes vertes.

- **T6.4** (`memory/arbitration.py`, pur + `arbitrage_cli.py` + `evidra arbitrer`) : `norm_conf`, `score_produit` (garde anti-double-pondération testée : produit exact), `score_noisy_or` (candidat T10.4 NON FIGÉ), `arbitrer` (ratio > seuil, `inf`/invalides ⇒ révision), `proteger_nouveaute` + `decider` (gel : isolé ×1 contre consensus ⇒ révision). Exemple §6.9 rejoué (0.135/0.302, ratio 2.26) : quorum pur 2.0 ⇒ B / 3.0 ⇒ révision ; avec gel, 1 vs 15 ⇒ révision même à 2.0 (amendement documenté, divergent de l'acceptation pré-amendement — assumé). CLI verrouillé : paires en conflit (relations distinctes) → MAINTENUE (+`update_status`) / INVALIDEE (+tombstone motivé, `retirer`) / révision ; seuils `[provisoire]` (`seuil_revision` strict par défaut) ; prod bloquée avant T10.4.
- Tests (6 + 1 CLI) : bornes, exemple §6.9, anti-double, nouveauté, invalides, noisy-or ; CLI 32 arêtes (gagnant MAINTENUE, perdant tombstoné, rebuild vérifié). Garde I3 mise à jour (6e écrivain revu). Compteur : **343 tests**, noyau 499/500, gardes vertes.

- **T6.5** : table directive (`aliases`, normalisée) câblée dans `OutilIngest` au démarrage ; `Envelope.etiquettes_brutes` (brut conservé, roundtrip WAL tolérant) ; `Memoire.candidats_alias()` (paires co-confirmées ≥ N=`n_confirmee`, graphe/index intacts, promus exclus, jamais automatique) ; `evidra aliases` (table + candidats, lecture seule). Homonymes inter-domaines distincts par construction (triplet porte le domaine).
- Tests `test_alias.py` (7) : convergence 3 variantes + brut, non-promu intact, exclusion promus, homonymes, rebuild brut, câblage démarrage, CLI. Compteur : **350 tests**, noyau 499/500, gardes vertes.

- **T6.6** (`memory/deduction.py` pur + `evidra deduire`, gate `deduction: disabled` par défaut) : chaînes A→B→C même relation, prémisses EXTRAITE seules, A→C absent, confiance `min`, 2 justifications (ids stables), span `Synthetic`, `ref derived://…`, `model_version sa-<harness>` ; consignation `add_edge` idempotente (verrou requis) ; `extract` ne voit que des documents (jamais d'enveloppes) ; anti-boucle I6 (`confirmer` refuse la dérivée, compteurs intacts).
- Tests `test_deduction.py` (7) : gate, chaîne min-justifiée, absence si lien direct, prémisses dérivées refusées (d→a + a→c dérivée ⇏ d→c), anti-boucle, fabrique, CLI (exit 2 si interdit, consigne + idempotent si permis).
- **T6.7** (`memory/ecarts.py` + section `ecarts` de `report` JSON/texte) : statuts, p50, jamais-confirmées, sous-seuil, tranches — déterministe, reproductible ; seuils jamais modifiés (§19). Test ajouté.
- **T6.8** : `phases["domaines"]["demarrage_a_froid"]` tracé ; UNCONFIRMED au jour 0 testé normal (validate sur graphe vide).
- Garde I3 resserrée (`self.flux(..).append` seul, `setdefault(..).append` exclu). **J6 clos.**
- Compteur : **360 tests**, noyau 499/500, `mypy` 21 fichiers, `lint-imports` KEPT, I9 7 constantes, offline vert.
