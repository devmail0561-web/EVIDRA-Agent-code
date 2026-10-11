# Evidra (SA) — Plan d'architecture, d'implémentation et de structure

**Auteur** : Michel Tendeng · **Date** : 2026-10-11 · **Base** : `ETUDE_SA.md` (2026-09-25) + amendements 2026-10-11
**Statut** : plan d'exécution — le SA n'existe pas encore ; ce document est le point de départ du dépôt `evidra`.

## 1. Cadrage

### 1.1 Objectif

Construire **Evidra**, un agent causal autonome, comme un projet Python **indépendant** qui importe le moteur GCN (`gcn-core` + `gcn-python`) comme bibliothèque. Le SA orchestre, persiste, décide, surveille et communique ; le moteur extrait, raisonne et valide. Rien du SA n'entre dans le moteur (seule exception licite : la frontière CIR, déjà portée par le Rust, cf. §18 de l'étude).

### 1.2 Périmètre

| Dans le périmètre (phases 0–9) | Hors périmètre (spec gelée, phase 10 gatée) |
|---|---|
| Harness modulaire (3 contrats, noyau < 500 SLOC) | `delegate` / sous-agents (ouverture P3 de l'étude) |
| Mémoire : WAL, snapshot, index, domaines, enveloppe | Index sémantique (déclencheur principal : taux d'UNCONFIRMED sur requêtes lexicales ; repli : 500 000 arêtes/domaine ou > 20 % de requêtes vides) |
| Boucle à 6 priorités, budgets, anti-famine, reçus | Déduplication sémantique par embeddings |
| Directives, permissions `can()`, tâches persistées | Chargement à chaud des compétences |
| Outils, validateur, moniteur, alertes | Entraînement / fine-tuning de modèles (reste dans le moteur) |
| API FastAPI, `/status`, formats adaptatifs | Graphe hiérarchique coarse-to-fine |
| Sécurité : canaux, signatures, quarantaines, anti-injection | Ed25519 multi-opérateurs (au 2ᵉ opérateur) |
| Dogfood domaine `code` 100 % offline | Calibration finale quorum/Nmax (bloquée par le gold, B3) |

### 1.3 Conventions

- **constaté** = prouvé dans le code du moteur ; **décidé** = norme du SA ; **provisoire** = valeur en attente de calibration, jamais figée en constante (elle vit dans la directive ou un fichier de config étiqueté `provisoire`).
- Les **phases** de ce plan (0 à 10) ne sont pas les **priorités** P1–P6 de la politique de sélection (§1.3 de l'étude), ni les niveaux P1–P3 de l'étude §12. Correspondance : phases 1–3 + 8 ≈ P1 de l'étude, phases 4–7 ≈ P2, phase 10 ≈ P3.
- Tailles indicatives (jours-homme, solo) : **S** ≤ 0,5 j · **M** 1–2 j · **L** 3–5 j. Estimations provisoires, à recaler après la phase 2.

## 2. Principes et invariants (exécutables, pas déclaratifs)

Chaque invariant est vérifié par un test ou une garde CI. Un invariant sans mécanisme de contrôle n'est pas un invariant.

| # | Invariant | Mécanisme d'application |
|---|---|---|
| I1 | Le SA n'importe du moteur que `analyze`, `analyze_batch`, `reason`, `reason_question`, `verify_path`, `CausalGraph` | `import-linter` (contrat « forbidden ») + test AST ; toute autre importation fait échouer la CI |
| I2 | Noyau (`kernel/`) < 500 SLOC et aucun nom concret d'outil/adaptateur | Test de comptage SLOC + test qui grep les noms de plugins dans `kernel/` |
| I3 | Un seul chemin d'écriture dans le graphe : `ingest()` (+ maintenance tracée) via le harness | `Store.append` n'est appelable que depuis `memory/` ; test de permissions |
| I4 | Aucune sortie causale sans provenance (`ref`, `span`, méthode, version, date) | Test de propriété sur toutes les sorties d'outils |
| I5 | `UNCONFIRMED` n'est jamais `FAUX` | Énumération fermée `Verdict` + test |
| I6 | Une arête `derived` ne confirme jamais ses prémisses et n'est jamais ré-ingérée par le moteur | Test SA explicite (le moteur ne l'interdit pas) |
| I7 | Le moteur ne voit jamais l'enveloppe SA ni le contexte de conversation | Pont moteur typé : n'accepte que `(kw_from, kw_to, graph, budget)` / texte |
| I8 | Défaut tout-interdit sauf `read` ; `delete` exige un motif WAL | `can(tool, verb, scope)` + suite adversariale |
| I9 | Aucun nombre dépendant de B3/B4 en constante de code | Lint : constantes `provisoire` lues depuis la config, refus si hardcodées |
| I10 | Noyau 100 % offline | `pytest --disable-socket` sur la suite dogfood `code` |
| I11 | Le contenu ingéré est une donnée citée, jamais une instruction | Corpus adversarial (§28 de l'étude) rejoué sur chaque adaptateur |
| I12 | Échec = fail-closed ; lecture WAL tolérante par ligne (skip + compteurs, jamais d'abort) | Tests de fautes (troncature, CRC invalide, ligne vide) |

## 3. Architecture

### 3.1 Vue en couches

```
COUCHE EXTERNE (décrite par directive, jamais en dur)
  fichiers · flux HTTP · agents pairs · LLM · humains
        │ poll / push / requêtes
        ▼
┌──────────────────────── HARNESS EVIDRA ─────────────────────────────┐
│ kernel/   contrats (Tool, Adapter, Store) · registry · scheduler · gate │
│ adapters/ local_files · http_feed · agent_push   (plugins)              │
│ tools/    extract · ingest · query_* · validate · alert · report · …    │
│ security/ plafonds de canal · signatures · quarantaines · détecteurs    │
│ monitor/  conditions · alertes                                          │
│ output/   formateurs LLM / humain / agent / alerte                      │
│ api/      FastAPI (/analyze /ingest /validate /query/* /status …)       │
└───────────┬──────────────────────────────┬──────────────────────────────┘
            │ coquilles minces             │ lit / écrit via Store
            ▼                              ▼
   MOTEUR (lib externe)           MÉMOIRE (= intelligence)
   analyze · reason · verify_path  WAL + snapshot par domaine, index,
   (+ MODÈLES = artefacts hashés,   enveloppes, registres (sources, alias,
    consommés, jamais modifiés)     modèles, tâches)
```

### 3.2 Modèle d'exécution (décidé)

- **Un seul thread propriétaire de la mémoire** (le *scheduler*). Aucun verrou applicatif sur le graphe : le single-writer est la garantie de cohérence.
- L'API (thread/event-loop séparé) **n'accède jamais à la mémoire** : elle dépose un événement (P1–P3) dans une file thread-safe avec un `Future`, le scheduler le traite dans l'ordre de priorité et résout le `Future`. Latence ajoutée = au plus un tick (réveil immédiat sur événement via `queue.get(timeout=…)`).
- À chaque tick : observer → évaluer P1…P6 dans l'ordre → **un seul outil principal par niveau actif**, séquentiel → lire le reçu avant de continuer → écrire au WAL. Anti-famine : P4–P6 garantis d'un slot minimal par cycle (quota défini en directive).
- Aucune condition vraie = cycle no-op (cible < 10 ms).
- Le noyau est synchrone ; aucun appel lourd ne tourne dans le thread du scheduler : `analyze_batch`, chargements de modèles et `httpx` s'exécutent en worker avec timeout issu de la directive (pas d'async dans le noyau) ; dépassement = reçu `degrade` + `budget:`, jamais de blocage des alertes P1 ni de l'API (`max_cycle_ms` ne peut pas interrompre un appel en cours).

### 3.3 Flux de référence

| Flux | Séquence |
|---|---|
| F1 Ingestion | `poll → extract (analyze_batch) → enveloppement ref/span → seuils directive → plafond de canal → ingest → WAL` ; rejet = `dropped` compté |
| F2 Cycle | situation → 6 priorités → `can()` → exécution → contexte borné (`truncated: n`) → reçu → WAL |
| F3 Requête | index O(k) → `reason()` (Dijkstra `-ln(conf)` côté moteur) → preuves + `min(prémisses)` → `ToolResult` |
| F4 Validation | claim → `CONFIRMED` / `UNCONFIRMED` / `CONTRADICTED`, sources citées |
| F5 Maintenance | `STALE` → re-confirmation ou arbitrage → `EN RÉVISION` → verdict ou tombstone |
| F8 Auto-interrogation | `/status`, état d'une tâche, cycle courant — lecture pure |

(F6 modèle-outil et F7 conversation relèvent de la phase 10.)

### 3.4 Décisions d'architecture (ADR courts)

| ADR | Décision | Justification | Alternative rejetée |
|---|---|---|---|
| 01 | Dépôt, package et `pyproject.toml` séparés du moteur ; dépendance `path` éditable, version pinnée à la première release du moteur | Séparation structurelle non négociable | Sous-package du moteur |
| 02 | WAL SA dédié (fsync par batch, `seq`, CRC, tombstones) | `SessionStore` : pas de fsync/lock/seq, suppressions non rejouables (constaté) | Réutiliser `SessionStore` |
| 03 | Single-writer + file d'événements | Cohérence sans verrous ; simplicité d'audit | Multi-thread avec locks fins |
| 04 | Noyau en stdlib uniquement (`dataclasses`, `typing.Protocol`) ; Pydantic v2 aux bords (directive, API, manifestes) | Noyau < 500 SLOC, zéro dépendance transitive dans le cœur | Pydantic partout |
| 05 | Découverte par entry-points `evidra_tools` / `evidra_adapters` (`importlib.metadata`) | Stdlib, plug-and-play, aucun nom concret dans le noyau | Registre codé en dur, `@register` |
| 06 | Politique de sélection **à règles**, pas de LLM orchestrateur | Déterministe, testable, offline | LLM planner |
| 07 | Partitionnement par domaine dès le jour 1 (layout disque + routage) | Multiplicateur de toutes les optimisations ; un refactor tardif coûte cher | Graphe global unique |
| 08 | Mises à jour de code = redémarrage ; de comportement = directive relue à chaque cycle (« tiède ») | 90 % du bénéfice du chaud, 0 % du risque (WAL sans lock en chaud = corruption prouvée) | Hot-reload |
| 09 | HMAC-SHA256 par agent (mono-opérateur), Ed25519 au 2ᵉ opérateur | Cas actuel : owner solo | Ed25519 d'emblée |
| 10 | `query_chain` = coquille mince sur `reason()` ; ne jamais réimplémenter Dijkstra côté SA | Le moteur Phase 3 le fait déjà | Dijkstra SA |

## 4. Stack technique

### 4.1 Choix retenus

| Domaine | Choix | Justification | Quand |
|---|---|---|---|
| Langage | **Python ≥ 3.11** (le moteur vise ≥ 3.10 ; le SA exige 3.11 pour `tomllib`, `StrEnum`, `ExceptionGroup`) | Même écosystème que `gcn-python` | P0 |
| Gestion de projet | **uv** + `pyproject.toml` (backend `hatchling`), `uv.lock` versionné | Résolution rapide, lock reproductible, `[tool.uv.sources]` pour la dépendance `path` du moteur | P0 |
| Noyau et mémoire | **stdlib** : `dataclasses`, `typing`, `json`, `os.fsync`, `zlib.crc32`, `hashlib`, `heapq`, `collections.OrderedDict`, `importlib.metadata`, `logging` | Noyau minimal, offline, auditable | P0–P3 |
| Verrou de fichier | **filelock** (verrou de processus sur le répertoire de données) | Évite deux instances sur un même WAL | P2 |
| Validation aux bords | **Pydantic v2** (directive, manifestes, API) + export JSON Schema | Schémas stricts, erreurs lisibles | P4 |
| API | **FastAPI** + **uvicorn** (extra `api`) | Dépendance côté SA assumée (absente du moteur) | P8 |
| Réseau | **httpx** (extra `network`), **feedparser** pour RSS/Atom | Adaptateur `http_feed`, `requires_network: true` | P9 |
| Surveillance fichiers | polling stdlib par défaut ; **watchfiles** en option | Le dogfood reste sans dépendance | P4 |
| Crypto | `hmac` + `hashlib` (stdlib) ; **cryptography** (extra) pour Ed25519 plus tard | HMAC suffit en mono-opérateur | P9 / P10 |
| CLI | **argparse** (entry-point `evidra`) | Pas d'over-engineering | P4 |
| Config / directive | **JSON** (format de l'étude), schéma Pydantic ; TOML pour la config d'exploitation | Conforme à l'étude | P4 |
| Logs | `logging` stdlib, formateur JSON maison (≈ 30 lignes) | Traçabilité sans dépendance | P1 |
| Tests | **pytest**, **hypothesis** (propriétés WAL), **pytest-benchmark** (SLO), **pytest-socket** (offline), **pytest-cov** | Une couche de test par risque (cf. §8) | P0 |
| Qualité | **ruff** (lint + format), **mypy --strict** sur `kernel/` et `memory/`, **import-linter**, script SLOC | Les gardes I1/I2 deviennent des échecs de build | P0 |
| CI | **GitHub Actions** (matrice 3.11/3.12) ; job « offline » distinct | Reproductibilité | P0 |
| Docs | Markdown dans `docs/`, ADR numérotés | Cohérent avec tes autres dépôts | P0 |

### 4.2 Groupes de dépendances

```toml
[project]
name = "evidra"
requires-python = ">=3.11"
dependencies = ["gcn-python", "filelock", "pydantic>=2"]

[project.optional-dependencies]
api     = ["fastapi", "uvicorn"]
network = ["httpx", "feedparser"]
crypto  = ["cryptography"]          # P10 (multi-opérateurs)

[dependency-groups]
dev = ["pytest", "hypothesis", "pytest-benchmark", "pytest-socket",
       "pytest-cov", "ruff", "mypy", "import-linter"]

[tool.uv.sources]
gcn-python = { path = "../gcn-python", editable = true }   # pinné à la 1re release

[project.scripts]
evidra = "evidra.cli:main"

[project.entry-points."evidra_tools"]      # outils intégrés
extract = "evidra.tools.extract:ExtractTool"
# … un entry-point par outil (jamais de liste dans le noyau)
```

### 4.3 Explicitement refusé ou reporté

- **Pas de LLM orchestrateur** (décision de l'étude) ; pas de LangChain/agent frameworks.
- **Pas de base de données** (SQLite/Neo4j) : le WAL JSONL + index mémoire suffit jusqu'à 500 000 arêtes/domaine ; à ré-évaluer seulement si les SLO échouent.
- **Pas de FAISS/fastText** avant le seuil de l'étude (garde `semantic_index_min_edges` en directive).
- **Pas d'`asyncio` dans le noyau**, pas de Celery/Redis, pas de Docker avant la phase 8.
- **orjson** : à n'introduire qu'après profilage montrant que `json` limite le débit du WAL.

## 5. Structure du projet

```
evidra/
├─ pyproject.toml · uv.lock · README.md · LICENSE
├─ .importlinter                     # contrats I1 (moteur) et I2 (noyau)
├─ docs/
│  ├─ ETUDE_SA.md                    # source de vérité de la conception
│  ├─ adr/                           # 0001-… (une décision = un fichier)
│  ├─ contrats/                      # harness-1.0.md, directive.schema.json
│  └─ runbook.md                     # exploitation, reprise après crash
├─ src/evidra/
│  ├─ kernel/                        # < 500 SLOC, stdlib seule
│  │  ├─ contracts.py                # Tool, Adapter, Store, ToolResult, RawDoc, Verb
│  │  ├─ registry.py                 # découverte + cycle de vie des plugins
│  │  ├─ scheduler.py                # 6 priorités, budgets, anti-famine, reçus
│  │  └─ gate.py                     # can(tool, verb, scope)
│  ├─ memory/
│  │  ├─ wal.py                      # append fsync-batch, seq, CRC, replay toléré
│  │  ├─ snapshot.py                 # snapshot versionné + .prev, compaction
│  │  ├─ store.py                    # façade Store (streams par domaine/registre)
│  │  ├─ envelope.py                 # CIR-noyau immuable + état mutable SA
│  │  ├─ index.py                    # label/tokens/domain/relation/conf-tiers
│  │  ├─ cache.py                    # LRU + node_to_cache_keys
│  │  ├─ lifecycle.py                # NOUVELLE→…→INVALIDÉE, décroissance
│  │  ├─ arbitration.py              # score composite + quorum (provisoire)
│  │  ├─ sources.py                  # registre de sources calculé
│  │  ├─ aliases.py                  # table d'alias lexicale par domaine
│  │  ├─ models.py                   # registre de modèles par hash
│  │  └─ tasks.py                    # file de tâches JSONL (ABANDONED tracé)
│  ├─ engine_bridge/                 # SEUL module important `gcn`
│  │  ├─ extract.py · reason.py · validate.py   # coquilles minces, logique nulle
│  │  └─ provenance.py               # enveloppement ref/span réels
│  ├─ directive/                     # schema.py, loader.py, reload.py (tiède)
│  ├─ tools/                         # outils intégrés (1 fichier = 1 outil + manifeste)
│  ├─ adapters/                      # local_files.py · http_feed.py · agent_push.py
│  ├─ security/                      # channels.py · signing.py · content.py · quarantine.py
│  ├─ monitor/                       # conditions.py · alerts.py
│  ├─ output/                        # llm.py · human.py · agent.py · alert.py
│  ├─ api/                           # app.py · routers/ · deps.py
│  ├─ boot/                          # phases 1–5, manifest.py, report.py
│  └─ cli.py
├─ directives/                       # code.dogfood.json, exemples cti.json
├─ tests/
│  ├─ unit/ · contract/ · integration/
│  ├─ fault/                         # crash simulé, troncature WAL, CRC
│  ├─ adversarial/                   # corpus injection (§28), permissions can()
│  ├─ offline/                       # suite dogfood sous --disable-socket
│  └─ bench/                         # SLO latence, 72 h de charge (script)
├─ calibration/                      # scripts §16.2 (phase 10, gatée)
├─ benchmarks/                       # corpus et runner du benchmark agentique MVP
└─ .github/workflows/                # ci.yml · offline.yml · bench.yml
```

**Règles de dossier** : `kernel/` ne connaît ni `memory/` ni `tools/` (il dépend uniquement des Protocols) ; `engine_bridge/` est le seul module autorisé à importer `gcn` ; `tools/` et `adapters/` n'importent jamais `memory/` directement (accès via `ctx.store`, filtré par `can()`). Écart assumé : la table de politique (`src/evidra/policy.py`, T4.3) vit hors du noyau, car le noyau ne nomme aucun outil.

## 6. Contrats et modèle de données

### 6.1 Contrats `harness/1.0` (squelettes)

```python
class Status(StrEnum):
    OK = "ok"; DEGRADE = "degrade"; REFUSED = "refused"; FAILED = "failed"

@dataclass(frozen=True, slots=True)
class ToolResult:
    status: Status
    payload: Mapping[str, Any]
    warnings: tuple[str, ...] = ()
    cost: Cost = Cost(ms=0, calls=0)
    trace_ref: int | None = None        # seq WAL du reçu

class Tool(Protocol):
    name: ClassVar[str]; version: ClassVar[str]          # semver
    harness_required: ClassVar[str]                      # ex. "1.0"
    input_schema: ClassVar[Mapping]; output_schema: ClassVar[Mapping]
    cost_hint: ClassVar[CostHint]
    side_effects: ClassVar[frozenset[Verb]]
    def run(self, ctx: Context, args: Mapping[str, Any]) -> ToolResult: ...

class Adapter(Protocol):
    requires_network: ClassVar[bool]
    def poll(self, since: Cursor | None) -> list[RawDoc]: ...
    def ack(self, cursor: Cursor) -> None: ...

class Store(Protocol):
    def append(self, stream: str, record: Record) -> int: ...   # retourne seq
    def lookup(self, stream: str, key: str) -> Record | None: ...
    def snapshot(self, stream: str) -> None: ...
```

`Verb` = `read | ingest | modify | delete | alert | egress`. `refused` (rejet par `can()`) est une **décision tracée**, pas une erreur. Le scheduler ne chaîne jamais deux outils sans avoir lu le reçu du précédent.

### 6.2 Enveloppe SA (§6.8 de l'étude)

```json
{
  "cir": { "source": "n001", "target": "n002", "relation": "cause",
           "attributes": {"confidence": 0.87, "explicit": true, "negated": false},
           "provenance": {"ref": "…", "span": [10240, 10287],
                          "extraction_method": "symbolic_rust",
                          "model_version": "gcn-core-x.y.z", "extracted_at": "…"} },
  "status": "NOUVELLE", "confirmation_count": 1,
  "last_confirmed_at": "…", "source_reliability": 0.5,
  "ingest_channel": "local_files", "derivation": "extracted",
  "quarantine": null
}
```

`cir` est immuable et stocké tel quel ; tout le reste est mutable et géré par `memory/`.

### 6.3 Ligne de WAL

```json
{"seq": 42, "ts": "…", "op": "add_edge", "domain": "code",
 "key": "<sha256 sans champs volatils>", "data": {…}, "crc": "9f3a1c2e"}
```

- `op` ∈ `add_edge | update_status | confirm | tombstone | source_stat | alias | task | receipt`.
- `crc` = CRC32 du JSON canonique de la ligne sans `crc` ; `seq` strictement croissant par stream.
- **Clé de dédup** = hash de `(domaine, label source normalisé, relation, label cible normalisé, ref, span, extraction_method, model_version)` — **sans** `extracted_at`, statut, compteurs, ni `param_epoch`.
- Rejeu : ligne invalide ⇒ `skipped += 1` + motif, jamais d'abort ; trou de `seq` ⇒ avertissement au rapport de démarrage.

### 6.4 Disposition disque

```
<data_dir>/
├─ sa_manifest.json                 # versions harness/directive, hash moteur attendu, seq
├─ domains/<domaine>/{snapshot.json, snapshot.json.prev, wal.jsonl}
└─ registry/{sources,aliases,models,tasks}/{snapshot.json, snapshot.json.prev, wal.jsonl}
```

Tous les streams partagent le **même code WAL** (un seul mécanisme à prouver).

## 7. Plan de réalisation — phases et tâches

### 7.1 Vue d'ensemble

L'ordre suit le §21 de l'étude : **WAL avant boucle**, boucle avant API, calibration en dernier. Chaque phase se termine par un **jalon** vérifiable ; on n'entame pas la suivante tant que les critères d'acceptation du jalon ne sont pas verts.

| Phase | Objectif | Jalon | Dépend de | Gate externe |
|---|---|---|---|---|
| 0 | Scaffolding + garde-fous CI | J0 | — | — |
| 1 | Noyau du harness (3 contrats, registre, `can()`, scheduler) | J1 | 0 | — |
| 2 | Mémoire : WAL, snapshot, index, enveloppe, domaines, registres | J2 | 1 | — |
| 3 | Pont moteur, provenance, ingestion, dogfood `code` offline | J3 | 2 | moteur installé |
| 4 | Directives, politique à 6 priorités, boucle, démarrage en 5 phases | J4 | 3 | — |
| 5 | Outils de lecture, validateur, cache, formats de sortie | J5 | 4 | — |
| 6 | Cycle de vie, arbitrage (provisoire), registre de sources, alias | J6 | 5 | — |
| 7 | Moniteur et alertes | J7 | 6 | — |
| 8 | API FastAPI + `/status` | J8 | 5 (7 recommandé) | — |
| 9 | Sécurité inter-agents/contenu + adaptateurs réseau | J9 | 8 | — |
| 10 | Calibration §16.2, benchmark agentique, ouverture P3 | J10 | 9 | **B1–B4** (gold ≥ 3000, checkpoint re-mesuré) |

Les phases 5 et 8 peuvent se recouvrir après J4 si l'on travaille seul sur peu d'heures : la phase 8 n'a besoin que des outils de la phase 5.

---

## Phase 0 — Scaffolding et garde-fous (J0)

#### T0.1 — Initialiser le dépôt (S)
- **Livrables** : dépôt `evidra/` hors workspace du moteur, `pyproject.toml` (§4.2), layout `src/`, `README.md`, `.gitignore`, copie de `ETUDE_SA.md` dans `docs/`.
- **Détail** : `uv init --package`, backend `hatchling`, Python 3.11, arborescence vide de l'§5 avec `__init__.py`.
- **Acceptation** : `uv sync && uv run pytest` passe sur un test trivial ; `import evidra` fonctionne.

#### T0.2 — Dépendance du moteur (S)
- **Livrables** : entrée `[tool.uv.sources]` en `path` éditable, `docs/engine-compat.md` (version/commit du moteur, hash attendu).
- **Détail** : confirmer le nom exact du module d'import dans le `pyproject.toml` de `gcn-python` ; écrire un test de fumée `tests/integration/test_engine_smoke.py` : `analyze` sur une phrase FR et une EN renvoie un CIR (dict) avec clés `provenance` attendues ; enregistrer la version pinnée à la première release du moteur.
- **Acceptation** : test de fumée vert ; le fichier de compat nomme la version consommée.

#### T0.3 — Qualité statique (S)
- **Livrables** : config `ruff` (lint + format), `mypy --strict` sur `kernel/` et `memory/` (régime plus souple ailleurs), `pre-commit` optionnel.
- **Acceptation** : `ruff check`, `ruff format --check` et `mypy` verts sur le squelette.

#### T0.4 — Garde I1 : frontière moteur (S)
- **Livrables** : `.importlinter` (contrat « forbidden » : seul `evidra.engine_bridge` peut importer le moteur), `tests/unit/test_engine_boundary.py` (parcours AST du paquet : à l'exception de la liste blanche `analyze`, `analyze_batch`, `reason`, `reason_question`, `verify_path`, `CausalGraph`, tout autre import `gcn*` échoue).
- **Acceptation** : un fichier fixture important un symbole interdit fait échouer le test (test « canari »), puis est supprimé du chemin de collecte.

#### T0.5 — Garde I2 : noyau < 500 SLOC (S)
- **Livrables** : `scripts/sloc.py` (lignes non vides hors commentaires/docstrings de `kernel/`), `tests/unit/test_kernel_budget.py`.
- **Détail** : le test vérifie aussi qu'aucun nom concret de plugin (`local_files`, `http_feed`, `validate`, …) n'apparaît dans `kernel/`.
- **Acceptation** : le test échoue dès 500 SLOC ou si un nom concret est ajouté.

#### T0.6 — Intégration continue (M)
- **Livrables** : `.github/workflows/ci.yml` (matrice 3.11/3.12 : ruff, mypy, `lint-imports`, pytest + couverture), `offline.yml` (pytest avec `--disable-socket`, activé dès T3.8), `bench.yml` (manuel, SLO).
- **Acceptation** : une PR de test avec un import interdit est rejetée par la CI.

#### T0.7 — ADR initiaux (S)
- **Livrables** : `docs/adr/0001–0010` (les dix décisions du §3.4) + modèle d'ADR (contexte, décision, conséquences, alternative rejetée).
- **Acceptation** : chaque ADR référence la section de l'étude qui le fonde.

**Jalon J0** : CI verte, garde I1 et I2 opérationnelles, moteur importable depuis le SA.

---

## Phase 1 — Noyau du harness (J1)

#### T1.1 — Contrats (`kernel/contracts.py`) (M)
- **Dépend de** : T0.1
- **Livrables** : `Status`, `Verb`, `Cost`, `CostHint`, `ToolResult`, `RawDoc`, `Cursor`, `Context`, `Record` ; Protocols `Tool`, `Adapter`, `Store` (§6.1) ; `HARNESS_VERSION = "1.0"`.
- **Détail** : `@runtime_checkable` où utile ; objets immuables (`frozen=True, slots=True`) ; `ToolResult` total : jamais d'exception brute qui traverse la frontière d'un outil.
- **Acceptation** : `tests/contract/` valide un plugin factice conforme et rejette un plugin non conforme (champ manquant, mauvais type).

#### T1.2 — Manifeste de plugin (S)
- **Dépend de** : T1.1
- **Livrables** : structure `Manifest` (`name`, `version` semver, `harness_required`, `permissions`, `channels`, `cost_hint`, `input_schema`, `output_schema`, `requires_network`) et validation stdlib dans le noyau.
- **Détail** : pas de Pydantic dans le noyau (ADR-04) ; validation minimale structurelle ; le schéma riche est vérifié au bord (`directive/`).
- **Acceptation** : manifeste absent ou incomplet ⇒ plugin refusé (fail-closed), motif tracé.

#### T1.3 — Registre et cycle de vie des plugins (`kernel/registry.py`) (L)
- **Dépend de** : T1.2
- **Détail** : découverte via `importlib.metadata.entry_points(group="evidra_tools")` et `"evidra_adapters"` ; états `discovered → validated → enabled → running → disabled | quarantined` ; trois échecs de contrat consécutifs ⇒ `quarantined` automatique ; `harness_required` supérieur à la version supportée ⇒ `disabled` avec motif ; code des compétences chargé « eager » (kilo-octets), poids de modèle jamais chargés ici ; rapport de découverte écrit (liste, état, motif).
- **Acceptation** : tests avec entry-points factices (monkeypatch de `importlib.metadata`) couvrant chaque transition ; aucune référence à un nom concret dans le registre.

#### T1.4 — Porte de permissions (`kernel/gate.py`) (M)
- **Dépend de** : T1.1
- **Détail** : `can(tool, verb, scope) -> Decision(allowed, motif)` ; matrice `allowed/forbidden` fournie par la directive (objet pur passé en paramètre) ; défaut : tout interdit sauf `read` ; `delete` exige un `motif` qui part au WAL ; chaque refus devient un `ToolResult(status=refused)` traçable.
- **Acceptation** : suite adversariale initiale (`tests/adversarial/test_gate.py`) : verbe inconnu, scope vide, héritage par élargissement, `forbidden` prioritaire sur `allowed`, `delete` sans motif.

#### T1.5 — Scheduler (squelette) (`kernel/scheduler.py`) (L)
- **Dépend de** : T1.3, T1.4
- **Détail** : boucle mono-thread ; file d'événements thread-safe avec `Future` pour P1–P3 (réveil immédiat) ; évaluation numérique des niveaux 1–6 sur des *conditions fournies* (callables enregistrés), le noyau ne nomme aucun outil ; un seul outil principal par niveau, séquentiel ; lecture du reçu avant de continuer ; budgets par cycle (`max_tool_calls`, `max_ingest_per_cycle`, `max_cycle_ms`, `max_wal_bytes`) avec dépassement tracé `budget:` ; anti-famine : slot minimal garanti P4–P6 ; arrêt propre sur signal.
- **Acceptation** : tests (1) ordre strict des priorités, (2) deux conditions de niveaux différents ⇒ traitement séquentiel dans l'ordre, (3) flux P4 saturé ⇒ P5/P6 reçoivent leur slot, (4) dépassement de budget tracé, (5) cycle no-op < 10 ms (SLO P2 de l'étude).

#### T1.6 — Journalisation et erreurs (S)
- **Livrables** : `evidra/logging.py` (formateur JSON, identifiant de corrélation par tick), hiérarchie `EvidraError → ContractError, BudgetExceeded, PermissionDenied, DirectiveError`.
- **Acceptation** : chaque reçu produit une ligne de log structurée avec `tick`, `tool`, `status`, `cost`.

#### T1.7 — Test de non-régression architecturale (S)
- **Dépend de** : T1.5
- **Détail** : un outil et un adaptateur fictifs, installés uniquement via entry-points de test, exécutent un tick complet **sans toucher au noyau** (§13.6 de l'étude).
- **Acceptation** : si ce test exige une modification de `kernel/`, le design du plugin est considéré comme fautif.

**Jalon J1** : noyau < 500 SLOC, `mypy --strict` vert, suite de contrat verte, aucune dépendance du noyau vers `memory/`, `tools/` ou le moteur.

---

## Phase 2 — Mémoire de connaissance (J2)

#### T2.1 — WAL append-only (`memory/wal.py`) (L)
- **Dépend de** : T1.1
- **Détail** : un stream = un fichier `wal.jsonl` ; `seq` strictement croissant ; CRC32 sur JSON canonique ; `fsync` par batch (seuil en nombre de lignes ou en ms, **provisoire** et configurable) ; `fsync` du répertoire à la création ; verrou `filelock` sur `data_dir` pour interdire deux instances ; rejeu tolérant (ligne invalide ⇒ skip + compteurs `skipped`, `crc_failed`, `seq_gap` ; dernière ligne tronquée ignorée et journalisée).
- **Acceptation** : test de propriété `hypothesis` (toute séquence d'opérations ⇒ rejeu égal à l'état attendu) ; test de faute : `kill -9` d'un sous-processus en cours d'écriture ⇒ **0 perte** des lignes déjà `fsync`ées (SLO P1 : intégrité après crash).

#### T2.2 — Snapshot et compaction (`memory/snapshot.py`) (M)
- **Dépend de** : T2.1
- **Détail** : snapshot `{version, last_seq, state}` écrit en tmp → `fsync` → rename atomique ; ancien snapshot conservé en `.prev` ; compaction déclenchée sur taille en octets (`max_wal_bytes`) et sur commande explicite ; chargement = snapshot + rejeu de `seq > last_seq` (pas de re-snapshot systématique qui masquerait une corruption) ; snapshot corrompu ⇒ repli sur `.prev` + rejeu plus long, signalé au rapport ; tombstones rejouables sans forcer de snapshot.
- **Acceptation** : injection de faute à **chaque** étape de la compaction (avant tmp, après tmp, après rename, avant truncation) ⇒ état rechargé identique.

#### T2.3 — Enveloppe CIR-noyau / état SA (`memory/envelope.py`) (M)
- **Dépend de** : T2.1
- **Détail** : `CirCore` immuable (`frozen`) ; `Envelope` mutable (`status`, `confirmation_count`, `last_confirmed_at`, `source_reliability`, `ingest_channel`, `derivation`, `quarantine`, `justifications`) ; deux clés distinctes : **clé d'observation** (§6.3, sert à la dédup du rejeu) et **clé de triplet** `(domaine, src normalisé, relation, dst normalisé)` (sert à compter les confirmations) ; une arête `derived` exige deux justifications et ne peut pas être ingérée comme source d'une confirmation.
- **Acceptation** : modifier `cir` lève une erreur ; test I6 : une arête `derived` ne change jamais `confirmation_count` de ses prémisses.

#### T2.4 — Domaines et façade `Store` (`memory/store.py`) (M)
- **Dépend de** : T2.2, T2.3
- **Détail** : un graphe par domaine, créé à la demande selon la directive ; routage des requêtes par domaine ; sous-domaines `descriptif`/`normatif` via un champ `subdomain` ; implémentation du Protocol `Store`.
- **Acceptation** : une requête dans le domaine A ne lit jamais les structures du domaine B (test sur compteurs d'accès).

#### T2.5 — Index (`memory/index.py`) (M)
- **Dépend de** : T2.4
- **Détail** : `label_index`, `tokens_index`, `domain_index`, `relation_index`, `confidence_tiers` (seuils 0.85/0.65 de l'étude, **provisoires**) ; construction unique après chargement, mise à jour O(1) à l'insertion, retrait propre sur tombstone ; normalisation des labels (casse, accents, espaces) dans une fonction unique réutilisée par la table d'alias.
- **Acceptation** : test de propriété « index ≡ scan linéaire » ; benchmark : `find_causes` p99 < **50 ms** sur 100 000 arêtes (SLO P1).

#### T2.6 — Registres (sources, alias, modèles, tâches) (M)
- **Dépend de** : T2.1
- **Détail** : quatre streams WAL partageant le même code ; `tasks` : `id`, `type`, `budget`, `deadline`, `état`, expiration ⇒ `ABANDONED` avec motif ; curseurs d'adaptateurs stockés comme enregistrements de type `cursor` dans `tasks` ; `models` : `{hash, chemin, version_moteur, statut}` (vide tant que B2 n'est pas levé).
- **Acceptation** : rejeu tolérant par ligne sur chaque registre ; une tâche expirée est marquée `ABANDONED` et non supprimée.

#### T2.7 — Rapport de chargement (S)
- **Livrables** : `LoadReport {snapshot_loaded, replayed, skipped, crc_failed, seq_gaps, duration_ms}` par stream, consommé par la phase 2 du démarrage.

#### T2.8 — Banc de mesure (S)
- **Livrables** : générateur de graphes synthétiques CTI (10k/100k/500k arêtes), `tests/bench/` (`pytest-benchmark`), écriture par rapport JSON daté.
- **Acceptation** : les SLO de la phase P1 sont mesurés (et non plus des cibles) pour le chargement, `find_causes`, l'insertion.

**Jalon J2** : crash simulé sans perte, compaction à l'épreuve des fautes, index équivalent au scan, SLO de requête mémoire mesurés.

---

## Phase 3 — Pont moteur, provenance, dogfood (J3)

#### T3.1 — Coquille `extract` (`engine_bridge/extract.py`) (M)
- **Dépend de** : T0.2, T1.1
- **Détail** : `extract(docs) → list[CIR]` via `analyze_batch` (dédup par lots déjà prouvée côté moteur), **exécuté en worker avec timeout de directive** (P3) ; **logique nulle** ; erreurs du moteur converties en `ToolResult(failed)` ; copies profondes en entrée et sortie (le cache `analyze` du moteur retourne une copie, on ne partage jamais de référence mutable).
- **Acceptation** : aucun import `gcn` hors de ce paquet (garde I1) ; entrée invalide ⇒ `failed`, jamais d'exception.

#### T3.2 — Enveloppement de provenance (`engine_bridge/provenance.py`) (M)
- **Dépend de** : T3.1
- **Détail** : le moteur Python émet `ref=None` et un `span` marqueur ; le SA injecte `ref` (document connu de l'adaptateur), `span` réel (`TokenSpan` pour le texte, `CodeSpan{file, line_start, line_end}` pour le code, `Synthetic` pour les dérivés) et `content_sha256` du texte source **par-dessus**, sans toucher aux autres champs du CIR-noyau ; revérification = re-hash + comparaison, échec ⇒ `ref_invérifiable` → quarantaine (§28.3). Aucune modification du moteur.
- **Acceptation** : un CIR du moteur (`ref=None`) ressort avec `ref` et `span` vérifiables contre le document source (I4).

#### T3.3 — Matérialisation d'un `CausalGraph` par domaine (M)
- **Dépend de** : T2.4
- **Détail** : construire/maintenir un `CausalGraph` moteur à partir des **CIR-noyau seuls** (l'enveloppe ne traverse jamais la frontière, I7) ; mise à jour incrémentale à l'ingestion ; invalidation/rafraîchissement via la méthode publique du moteur (jamais de lecture directe de son cache interne).
- **Acceptation** : le graphe matérialisé est identique à une reconstruction depuis le WAL.

#### T3.4 — Sous-graphe borné (M)
- **Dépend de** : T2.5, T3.3
- **Détail** : à partir de nœuds amorces trouvés par l'index, BFS limité (profondeur et plafonds nœuds/arêtes **provisoires**, à aligner sur les ordres de grandeur mesurés côté moteur : 500 nœuds / 2000 arêtes) ; écriture explicite `truncated: n` quand le plafond coupe.
- **Acceptation** : un domaine de 100k arêtes ne fait jamais passer plus que le plafond au moteur ; `truncated` présent dans le reçu.

#### T3.5 — Coquilles `reason` et `validate` (`engine_bridge/reason.py`, `validate.py`) (M)
- **Dépend de** : T3.3, T3.4
- **Détail** : `reason_chain → reason()` (paramètres moteur : budget 16, profondeur ≤ 2, top-k 5, passés en arguments, pas hardcodés) ; `validate → reason() + verify_path` ; sortie normalisée en `ToolResult` avec preuves et confiance de chaîne ; les résultats `derived` du moteur ne sont **jamais** ingérés. `query_chain` n'implémente pas Dijkstra (ADR-10).
- **Acceptation** : test de contrat : aucune arête `derived` n'entre dans `Store` via ces coquilles.

#### T3.6 — Outil `ingest` (L)
- **Dépend de** : T2.3, T2.5, T3.2
- **Détail** : pipeline F1 ; seuils d'admission de la directive (`min_confidence`, `min_extraction_method`) ; application de la table d'alias (T6.5 — passe-plat identité jusque-là) ; trois issues : *nouvelle arête* (NOUVELLE), *confirmation* (même triplet depuis une `ref` différente ⇒ `confirmation_count` + 1 et `last_confirmed_at`), *idempotent* (même observation rejouée ⇒ aucun effet) ; rejets comptés par motif dans `dropped` ; permission `ingest` vérifiée par `can()` ; reçu avec `trace_ref` = seq WAL.
- **Acceptation** : rejeu de la même source 2× ⇒ état identique ; deux sources distinctes ⇒ confirmation ; sous le seuil ⇒ `dropped` compté et tracé.

#### T3.7 — Adaptateur `local_files` (M)
- **Dépend de** : T1.1, T2.6
- **Détail** : `poll(since)` par `mtime` + hash de contenu ; `glob` et `watch` (polling stdlib) ; curseur persisté via `ack()` ; texte naturel → `TokenSpan`, fichiers `.py` → `CodeSpan` ; `requires_network = False`.
- **Acceptation** : modification d'un fichier ⇒ un seul `RawDoc` au poll suivant ; redémarrage ⇒ pas de re-traitement des fichiers inchangés.

#### T3.8 — Dogfood `code` de bout en bout (M)
- **Dépend de** : T3.6, T3.7
- **Détail** : directive `directives/code.dogfood.json` (domaine `code`, source `local_files` sur le dépôt `evidra`) ; ingestion de `docs/` et `src/` ; requêtes causes/effets avec provenance ; activation du job `offline.yml`.
- **Acceptation** : suite verte sous `pytest --disable-socket` (I10), zéro appel sortant, I4 vérifié.

#### T3.9 — Tranche verticale gold-219 (M) — *exigée §21(0) de l'étude, avant tout dimensionnement*
- **Dépend de** : T3.6
- **Détail** : `local_files` sur les 219 phrases du gold → `analyze_batch` → enveloppement `ref/span` → seuils → `ingest` → `validate` sur paires croisées ; sortie = 5 nombres (précision/rappel CONFIRMED, taux UNCONFIRMED, latence médiane/p99, docs/sec), même mauvais.
- **Acceptation** : les 5 nombres sont écrits et datés ; les budgets par cycle (T1.5) sont fondés dessus, pas sur les 4 timings op.

**Jalon J3** : le SA ingère son propre dépôt hors ligne, répond avec provenance, les 5 nombres de la tranche verticale sont écrits, et le moteur n'est touché que par les coquilles.

---

## Phase 4 — Directives, politique, boucle, démarrage (J4)

#### T4.1 — Schéma de directive (`directive/schema.py`) (M)
- **Dépend de** : T1.4
- **Détail** : modèles Pydantic v2 couvrant le §9.3 plus les ajouts décidés : `budgets` (`max_tool_calls`, `max_ingest_per_cycle`, `max_cycle_ms`, `max_wal_bytes`), quotas anti-famine, `channel_ceilings`, `aliases` par domaine, `permissions` (`allowed`/`forbidden` par verbe et scope), `staleness`, constantes de domaine `provisoire` (`T_domaine`, `Nmax`, `seuil_quorum`), `delegate: disabled`, `semantic_index_min_edges: 500000`, `trusted_agents` ; export JSON Schema vers `docs/contrats/directive.schema.json`.
- **Acceptation** : directive invalide ⇒ `DirectiveError` précis (chemin du champ) ; la directive du dogfood valide ; toute valeur `provisoire` est étiquetée comme telle dans le schéma (I9).

#### T4.2 — Chargement et rechargement « tiède » (`directive/loader.py`, `reload.py`) (M)
- **Dépend de** : T4.1
- **Détail** : directive relue à chaque cycle (comparaison mtime + hash) ; diff ⇒ activation/désactivation de plugins **sans redémarrage** (un plugin `disabled` est du code inerte) ; une directive invalide est rejetée et l'ancienne conservée, avec alerte ; hash de directive écrit dans un reçu WAL.
- **Acceptation** : désactiver `local_files` en cours d'exécution arrête le polling au cycle suivant.

#### T4.3 — Politique de sélection (`src/evidra/policy.py`) (M)
- **Dépend de** : T4.1, T1.5
- **Détail** : table priorité → condition → outil de l'§1.3 de l'étude (P1 alerte active → `alert`/`report` ; P2 claim → `validate` ; P3 question causale → `query_*` ; P4 données → `fetch → extract → ingest` ; P5 relations STALE → maintenance ; P6 fond → `query_cycles → query_gaps`). **Écart assumé par rapport à l'arborescence §5** : ce module vit hors du noyau, car le noyau ne nomme aucun outil (I2).
- **Acceptation** : la politique est testable sans moteur ni disque (conditions simulées) ; cycle sans condition ⇒ aucun outil.

#### T4.4 — Scheduler complet (L)
- **Dépend de** : T4.2, T4.3, T2.6
- **Détail** : intégration de la politique, des budgets et de l'anti-famine ; consommation de la file de tâches par P4–P6 ; contexte borné (`max_context_edges`, `max_tool_results`) avec dégradation par score et `truncated: n` ; seuls les reçus avec mutation écrivent au WAL (`op: receipt`) — no-op = zéro écriture, le coût alimente les compteurs (§26.1 de l'étude) ; « qu'a fait le SA ? » = lecture du WAL.
- **Acceptation** : test d'intégration — un claim (P2) et de nouvelles données (P4) arrivant ensemble sont traités dans cet ordre ; un budget dépassé produit un reçu `degrade` avec `budget:` ; aucune famine de P5/P6 sous charge P4.

#### T4.5 — Démarrage en cinq phases (`boot/`) (L)
- **Dépend de** : T2.7, T4.4
- **Détail** : (1) **manifeste** `sa_manifest.json` (versions harness/directive, hash moteur attendu, seq WAL) — divergence ⇒ mode `degraded` explicite, jamais de poursuite silencieuse ; (2) **WAL** : snapshot + rejeu seq/CRC + tombstones ; (3) **registres** : sources, alias, tâches (`ABANDONED` repris, deadlines réévaluées) ; (4) **moteur + modèles** : initialisation du moteur-lib, registre de modèles par hash (un seul chargement par hash), contrôle `param_epoch`, préchauffage optionnel ; (5) **boucle** : reprise des tâches persistées. Chaque phase écrit un rapport structuré. Sonde `requires_network` : composant réseau indisponible ⇒ `degraded:{composant, motif}`, jamais un crash. *Note* : le `pending` de clarification conversationnelle rejoindra la reprise en phase 10 (flux F7).
- **Acceptation** : `kill -9` puis redémarrage ⇒ même état mémoire et tâches reprises ; manifeste divergent ⇒ démarrage en `degraded` avec motif visible dans le rapport.

#### T4.6 — CLI (`cli.py`) (S)
- **Dépend de** : T4.5
- **Détail** : `evidra run --directive d.json --data-dir D`, `evidra ingest <chemin>`, `evidra query causes|effects <concept>`, `evidra compact`, `evidra status` (lecture seule du `data_dir`, rapport de chargement, en attendant l'API).
- **Acceptation** : `evidra run` démarre le dogfood et s'arrête proprement sur `SIGINT`/`SIGTERM`.

#### T4.7 — Cycle no-op et arrêt propre (S)
- **Acceptation** : cycle sans condition < 10 ms mesuré ; arrêt sur signal ⇒ WAL `fsync`é, verrou libéré, reçu final écrit.

**Jalon J4** : le dogfood `code` tourne en boucle, hors ligne ; un crash n'altère pas l'état ; une modification de directive change le comportement sans redémarrage.

---

## Phase 5 — Outils de lecture, validateur, cache, formats (J5)

#### T5.1 — `query_causes` / `query_effects` (M)
- **Dépend de** : T2.5, T3.4
- **Détail** : résolution du concept par l'index (exact → normalisé → token ; sous-chaîne bornée en dernier recours) ; chaque cause/effet renvoyé avec provenance, confiance, statut et fiabilité de source ; résultat vide = « aucune source », jamais une affirmation négative.
- **Acceptation** : p99 < 50 ms sur 100k arêtes (SLO P1) ; I4 vérifié sur 100 % des sorties.

#### T5.2 — `query_chain` (M)
- **Dépend de** : T3.5
- **Détail** : coquille mince sur `reason()` sur sous-graphe borné ; renvoie le(s) chemin(s) top-k, confiance de chaîne (produit) et provenance de chaque arête ; `min(prémisses)` pour tout résultat `derived`. **Ne jamais réimplémenter Dijkstra** (ADR-10). Le BFS bidirectionnel n'est à étudier (spike) que si le SLO échoue sur les chaînes longues.
- **Acceptation** : un chemin de 3 arêtes à 0.90 l'emporte sur un lien direct à 0.60 (comportement garanti par le moteur, test d'intégration côté SA).

#### T5.3 — `validate(claim)` (L)
- **Dépend de** : T3.5, T2.5
- **Détail** : entrée = texte (extrait en CIR candidat via `extract`) ou triplet structuré ; sorties fermées `CONFIRMED` (source citée + confiance), `UNCONFIRMED` (absent : ni preuve ni réfutation, **jamais « faux »**), `CONTRADICTED` (relation opposée présente, source citée + confiance) ; les arêtes `quarantined_content` sont exclues (I11). **Reprise de la table fermée §5 de l'étude** (paires opposées + négation + granularité ; hors table = `UNCONFIRMED`, ADR de simple traçage).
- **Acceptation** : trois verdicts couverts par tests ; p99 < 200 ms sur 50k arêtes (SLO P1) ; le taux de CONFIRMED correct est mesuré en phase 10 (gold), pas prétendu ici.

#### T5.4 — Spike : accès à `CYCLES`, `GAPS`, `PROVENANCE`, `RELIABILITY` (S)
- **Contexte** : l'étude précise que `CYCLES?`/`GAPS?` sont des requêtes Rust (CLI) non exposées par la mémoire Python.
- **Détail** : déterminer le chemin d'accès depuis le SA (binding Python du moteur ou appel du CLI Rust en sous-processus, stateless). Si seul le CLI Rust est possible, écrire un ADR amendant la liste blanche I1 pour un wrapper `subprocess` isolé dans `engine_bridge/`, avec timeout et schéma de sortie validé.
- **Acceptation** : ADR écrit (chemin retenu, coût, liste blanche mise à jour) avant T5.5.

#### T5.5 — Outils `query_cycles`, `query_gaps`, `counterfactual` (M)
- **Dépend de** : T5.4
- **Détail** : coquilles sur le moteur (catégorie `reason`, lecture seule) ; `query_gaps(chain)` ne s'applique qu'aux chaînes surveillées par la directive ; `counterfactual(concept)` = Pearl do-calculus du moteur sur sous-graphe borné, étiqueté comme calcul sur assertions sourcées (pas de contrôle de confondeurs — §2 de l'étude), jamais présenté comme fait établi.
- **Acceptation** : résultats sourcés ; aucun écrit dans le graphe.

#### T5.6 — Cache LRU à invalidation ciblée (`memory/cache.py`) (M)
- **Dépend de** : T5.1
- **Détail** : `query_cache[(keyword, relation, domain)]` + `node_to_cache_keys` ; insertion / confirmation / tombstone d'une arête `(src, dst)` n'invalide que les clés liées à `src` ou `dst` ; taille bornée (LRU) ; tag de cache incluant `param_epoch.current()` pour tout résultat dépendant du moteur ; le SA ne lit **jamais** le cache interne du moteur ; compteurs hits/misses/invalidations pour `/status`.
- **Acceptation** : test de propriété « résultat avec cache ≡ sans cache après toute séquence de mises à jour » ; requête répétée servie en O(1) mesuré.

#### T5.7 — Formateurs de sortie (`output/`) (M)
- **Dépend de** : T5.1–T5.3
- **Détail** : quatre destinataires — **LLM** (JSON compact : faits, sources, confiances, sans prose), **humain** (texte verbalisé, citations en fin de paragraphe, confiance en prose), **agent** (CIR complet + provenance, signature en phase 9), **alerte** (sévérité, condition, sous-graphe) ; citations toujours quotées et attribuées, jamais fusionnées au gabarit (I11). Gabarits de verbalisation côté SA : le verbaliseur du moteur n'est pas dans la liste blanche I1, l'importer exigerait un ADR.
- **Acceptation** : tests « golden » par destinataire ; aucune affirmation causale sans source (I4).

#### T5.8 — Outil `report(scope, format)` (M)
- **Détail** : rapport depuis la mémoire (relations nouvelles, conflits ouverts, relations STALE, chaînes surveillées) en JSON ou texte ; planifiable via `report_schedule` (tâche P5/P6).
- **Acceptation** : rapport reproductible à horloge figée.

#### T5.9 — Auto-interrogation interne (S)
- **Détail** : fonctions de lecture pure — `status()` → `{edges, nodes, domains, wal_seq, cache, epoch, uptime, degraded?}` ; état d'une tâche (`id`, état, budget consommé/restant, deadline, motif) ; cycle courant (`phase`, outil en cours, budget restant). Tous les compteurs existent déjà : seul le verbe manquait.

**Jalon J5** : toute requête renvoie un `ToolResult` sourcé ; les SLO `validate` et `query_causes` sont mesurés ; l'ADR de la règle d'opposition et celui de l'accès CYCLES/GAPS sont écrits.

---

## Phase 6 — Cycle de vie, arbitrage, registre de sources, alias (J6)

#### T6.1 — Machine d'états (`memory/lifecycle.py`) (M)
- **Détail** : `NOUVELLE → ACTIVE` (≥ 2 sources concordantes) `→ CONFIRMÉE` (≥ N sources, N en directive) `→ STALE` (non re-confirmée depuis T jours) `→ EN RÉVISION → MAINTENUE | INVALIDÉE` ; chaque transition = enregistrement WAL (`update_status`) avec motif ; transition illégale rejetée et comptée.
- **Acceptation** : test exhaustif de la matrice de transitions.

#### T6.2 — Décroissance temporelle (M)
- **Détail** : `freshness(t)` avec t = `published_at` du document source (extrait par l'adaptateur : frontmatter/RSS/file-mtime, sinon `unknown` ⇒ fraîcheur neutre 1.0 + flag), jamais la date d'ingestion (§6.9) ; `freshness(t) = exp(-(now − t) / T_domaine)` (constante de temps, vraie demi-vie = T·ln 2) ; `stale_after_days` et `invalidate_after_days` de la directive ; la confiance **effective** est calculée, le CIR-noyau n'est jamais modifié ; tâche de maintenance P5 ; horloge injectable.
- **Acceptation** : tests à horloge simulée (CTI 7 j, conformité 90 j, droit 365 j).

#### T6.3 — Registre de sources calculé (`memory/sources.py`) (M)
- **Détail** : compteurs (`relations_contributed`, `confirmed_by_independent_source`, `contradicted_by_higher_confidence`) → `confirmation_rate`, `contradiction_rate` ; `reliability = 0.7·confirmation_rate + 0.3·(1 − contradiction_rate)` (**provisoire**) ; plancher `n_min = 5` (en dessous : 0.5 neutre + statut `monitored` forcé) ; statuts `trusted` (≥ 0.80 et contradiction ≤ 0.05), `monitored` (0.60–0.80), `suspect` (contradiction > 0.10 ⇒ relations admises en NOUVELLE seulement), `blocked` (directive/audit) ; jamais déclaré à la main ; amorçage du registre en `monitored` (§20).
- **Acceptation** : une source qui contredit soudainement déclenche un signal consommable par le moniteur (phase 7).

#### T6.4 — Arbitrage des conflits (`memory/arbitration.py`) (L)
- **Dépend de** : T6.1, T6.2, T6.3
- **Détail** : `score = conf_extraction × reliability(source) × norm_conf(n) × freshness(t)` avec `norm_conf(n) = log₂(1+n) / log₂(1+Nmax)` plafonné à 1 ; règle de quorum « ratio > seuil ⇒ l'arête l'emporte, sinon EN RÉVISION » ; **valeurs `provisoires`** lues depuis la directive (étude : quorum 2.0 ; amendement : EN RÉVISION par défaut sous 3.0, retenu tant que la calibration n'existe pas) ; résolution `MAINTENUE` ou `INVALIDÉE` (tombstone avec motif — aucune suppression silencieuse, §2.3). **Garde de double-pondération** : ne pas multiplier un score d'arête qui intègre déjà la fiabilité de provenance du moteur par la fiabilité de source sans normalisation. Comparaison noisy-OR vs produit (§16.2) avant de figer ; premier rapporteur isolé contre consensus ⇒ `EN RÉVISION` (bonus `novelty` borné ou gel, jamais pénalité de fiabilité).
- **Acceptation** : l'exemple chiffré de l'étude (§6.9 : scores ≈ 0.135 et ≈ 0.302, ratio ≈ 2.24) est un test unitaire, rejoué avec seuil 2.0 (B l'emporte) puis 3.0 (reste EN RÉVISION) ; test dédié anti-double-pondération ; mise en production bloquée avant T10.4.

#### T6.5 — Alias lexicaux (`memory/aliases.py`) (M)
- **Détail** : table d'alias par domaine dans la directive (casse, sigles, variantes : « auth », « login », « authentification ») appliquée **avant** l'ingestion côté SA, en surcouche réversible (`label_brut` toujours conservé, homonymes inter-contextes = nœuds distincts) ; alias *candidats* produits par co-confirmation N fois, avec **promotion humaine obligatoire** (jamais automatique, §19).
- **Acceptation** : les trois variantes convergent vers un seul nœud dans l'index ; un candidat non promu ne change rien au graphe.

#### T6.6 — Déduction tracée (M)
- **Détail** : si A→B et B→C et A→C absent : arête `derivation: "derived"`, confiance = `min(conf(A→B), conf(B→C))`, deux justifications obligatoires, span `Synthetic` ; ne confirme jamais ses prémisses (I6), n'est jamais reçue par le moteur comme entrée d'ingestion ; interdit par défaut (`forbidden`), activé par directive.
- **Acceptation** : test I6 « anti-boucle » explicite ; confiance jamais augmentée par inférence libre.

#### T6.7 — Auto-apprentissage restreint (S)
- **Détail** : trois compteurs seulement — registre de sources, alias candidats, rapport d'écart seuils-vs-confirmations ; le SA ne modifie jamais ses seuils seul (§19).

#### T6.8 — Démarrage à froid (S)
- **Détail** : ingestion initiale tracée ; tout `UNCONFIRMED` au jour 0 est normal et écrit dans le rapport.

**Jalon J6** : le graphe vieillit, se confirme, arbitre ses conflits avec des constantes `provisoires` lues en config, et fusionne les alias lexicaux.

---

## Phase 7 — Moniteur et alertes (J7)

#### T7.1 — Conditions de surveillance (`monitor/conditions.py`) (M)
- **Détail** : conditions déclarées dans la directive (`watch_cycles`, `watch_gaps_in_chains`, `alert_on_new_relation_involving` en regex (validées au chargement, rejet des catastrophiques, timeout d'évaluation — anti-ReDoS), relation haute confiance invalidée, source fiable contredisant une croyance établie, conflit non résolu) ; chaque condition = fonction pure sur l'état ; évaluées en P1 (alerte active) et P6 (fond).
- **Acceptation** : chaque condition testable sans moteur ni disque.

#### T7.2 — Alertes (`monitor/alerts.py`) et outil `alert` (M)
- **Détail** : payload structuré (sévérité, condition déclenchante, sous-graphe, sources) ; déduplication (même condition + clé non réémise dans une fenêtre) ; état `active/acquittée` persisté au WAL ; sortie locale par défaut (JSONL) — l'envoi vers `alert_endpoint` est un `egress`, `requires_network`, et dégrade sans bloquer.
- **Acceptation** : réseau coupé ⇒ alerte conservée localement, composant `degraded`, cycle non bloqué.

#### T7.3 — Lacunes orientées objectif (M)
- **Détail** : `query_gaps` sur les chaînes surveillées ; formulation de la question « quelles sources acquérir pour compléter X→Y ? » ; création d'une tâche P4 budgétée ; une lacune en domaine surveillé prime sur un nœud orphelin hors périmètre.

#### T7.4 — Corpus d'événements et mesure (M)
- **Détail** : corpus synthétique CTI étiqueté (ground truth) ; mesure précision/rappel des alertes ; script de charge 72 h.
- **Acceptation** : cible de conception précision ≥ 0.80, rappel ≥ 0.75 (SLO P2) ; état de la mesure documenté — pas de valeur annoncée tant qu'elle n'est pas mesurée.

**Jalon J7** : les conditions de la directive déclenchent des alertes dédupliquées, tracées, dégradées proprement hors réseau.

---

## Phase 8 — API de service (J8)

#### T8.1 — Application FastAPI et pont de threads (`api/app.py`) (L)
- **Dépend de** : T5.7
- **Détail** : chaque requête dépose un événement P1–P3 + `Future` dans la file du scheduler (§3.2), attend avec timeout ; la mémoire n'est jamais touchée depuis le thread HTTP ; correspondance statut → HTTP : `ok` 200, `degrade` 200 + `warnings`, `refused` 403 (décision, corps explicite), `failed` 5xx ; scheduler démarré dans le `lifespan`.
- **Acceptation** : test de charge concurrent sans corruption ni deadlock ; une requête P2 double une tâche P4 en cours à son tick suivant.

#### T8.2 — Endpoints (L)
- **Détail** : `POST /analyze`, `POST /ingest`, `GET /query/causes/{concept}`, `GET /query/effects/{concept}`, `GET /query/chain/{from}/{to}`, `POST /validate`, `GET /status`, `POST /directive`, `GET /alerts` (§8.2) ; paramètres `domain` et `format=llm|human|agent` ; schémas Pydantic ; OpenAPI exporté dans `docs/contrats/`.
- **Acceptation** : chaque endpoint a un test de contrat ; `/analyze` n'a aucun effet de bord (verbe `read`).

#### T8.3 — Authentification et exposition (M) *(ajout du plan, hors étude)*
- **Détail** : jeton porteur local comparé en temps constant (`hmac.compare_digest`), lié aux verbes autorisés ; `POST /directive` nécessite le verbe `modify` **et** une directive signée (clé owner), chaque version entre au WAL (`directive:{version, auteur, motif}`), rollback testé vers la version précédente ; écoute sur `127.0.0.1` par défaut ; l'exposition externe est un choix explicite de directive.
- **Acceptation** : requête sans jeton ⇒ 401 ; jeton lecture seule sur `/ingest` ⇒ 403 tracé.

#### T8.4 — `/status` (S)
- **Détail** : expose F8 et `degraded: {composant, motif}` issu de la sonde `requires_network`.

#### T8.5 — Tests et mesures API (M)
- **Détail** : `TestClient`, charge concurrente, latences p99 ; l'API fonctionne hors ligne (boucle locale) ; job CI offline étendu.

#### T8.6 — Exécution et exploitation (S)
- **Livrables** : `evidra serve`, `docs/runbook.md` (démarrage, reprise après crash, compaction, rotation des clés), Dockerfile minimal optionnel (volume `data_dir`).

**Jalon J8** : le SA est consommable par un LLM, un humain ou un autre agent via HTTP ; l'API respecte le single-writer.

---

## Phase 9 — Sécurité et adaptateurs réseau (J9)

#### T9.1 — Plafonds de confiance par canal (`security/channels.py`) (M)
- **Détail** : `channel_ceilings` en directive (confiance maximale acceptée par canal : `local_files`, `http_feed`, `agent_push`, …) ; l'ingestion plafonne et trace `capped` ; valeurs **provisoires** (les confiances du moteur ne sont pas calibrées, B1).
- **Acceptation** : un flux HTTP injectant du 0.99 est plafonné et le plafonnement apparaît au reçu.

#### T9.2 — Signatures (`security/signing.py`) (M)
- **Détail** : enveloppe `signature: {algo, key_id, nonce, ts}` (fenêtre d'acceptation 5 min, nonce vu = rejet) ; **HMAC-SHA256**, une clé par agent (jamais partagée), stockage documenté (fichier 0600 + env, jamais repo/logs) ; rejet fail-closed si non signé ou algorithme hors liste, sans inspection du contenu ; rotation = remplacement de clé + reclassement `EN RÉVISION` des arêtes de l'agent depuis la date de compromission supposée.
- **Acceptation** : signature invalide, absente, algorithme inconnu, clé révoquée : quatre rejets distincts testés.

#### T9.3 — Adaptateur `agent_push` et autorité d'écriture (M)
- **Détail** : `trusted_agents` (domaines autorisés, `max_confidence_accepted`) ; tout CIR reçu entre en `NOUVELLE` avec `ingest_channel: "agent_push"` ; sortie de quarantaine **uniquement** après confirmation par un adaptateur non-agent (anti-Sybil) ; indépendance = adaptateurs de types différents **et** amonts distincts (`cite:[refs]` extraits par l'adaptateur : deux sources relayant le même amont = 1 confirmation, pas 2).
- **Acceptation** : N confirmations `agent_push` ne sortent jamais une arête de quarantaine ; un agent écrivant hors de son domaine est rejeté.

#### T9.4 — Détecteurs de contenu (`security/content.py`) (L)
- **Détail** : taxonomie fermée — `instruction`, `provenance_forgée`, `contradiction_fabriquée`, `saturation` (renvoi aux budgets) ; `ref_doc` résolvable au moment de l'ingestion ; offsets revérifiés contre le document ; contradiction d'une source fiable sans preuve ⇒ fardeau de la preuve sur l'arrivant ; seuils étiquetés `ARBITRAIRE + protocole` (calibrés sur le corpus T9.7, pas fixés ici).
- **Acceptation** : chaque menace produit un motif de quarantaine nommé et journalisé.

#### T9.5 — Quarantaine de contenu (M)
- **Détail** : `quarantined_content` : stocké (traçabilité), exclu des requêtes et des `CONFIRMED`, visible en audit ; sortie par arbitrage humain ou corroboration indépendante ; CLI `evidra quarantine list|release`.

#### T9.6 — Séparation donnée / instruction (M)
- **Détail** : `extract` sépare `texte_cité` de tout champ interprété ; audit des gabarits : aucune concaténation de texte source en position d'instruction.
- **Acceptation** : test statique sur les gabarits de `output/`.

#### T9.7 — Corpus adversarial (M)
- **Détail** : corpus figé minimal (« oublie tes instructions » ⇒ `instruction` ; faux `ref_doc` ⇒ `provenance_forgée` ; contradiction d'un claim du gold sans preuve ⇒ `contradiction_fabriquée`) avec verdicts attendus écrits ; runner paramétrique **rejoué contre chaque adaptateur** : un adaptateur ne passe `enabled` qu'après réussite.

#### T9.8 — Adaptateur `http_feed` (M)
- **Détail** : `httpx` en worker avec timeout de directive, `feedparser`, ETag/`If-Modified-Since`, backoff ; `requires_network: true` ; `ref` = URL résolvable ; hors ligne ⇒ `degraded` avec motif, jamais un crash ; coupure en cours de cycle ⇒ le cycle continue (jamais de blocage scheduler).
- **Acceptation** : coupure réseau en cours de cycle ⇒ le cycle continue ; corpus adversarial vert.

#### T9.9 — Sorties réseau contrôlées (S)
- **Détail** : tout appel sortant passe par le verbe `egress` et une liste blanche d'hôtes déclarée dans la directive.

#### T9.10 — Rétention et effacement (M) — *§17.6 de l'étude*
- **Détail** : politique par domaine (`retention_jours`, purge des preuves après délai, registre des suppressions versionné) ; la tombstone marque, la purge efface, les deux tracées ; sans politique écrite, retirer `conformite_rgpd` des exemples.
- **Acceptation** : purge d'un doc ⇒ preuve illisible + suppression enregistrée.

**Jalon J9** : un document hostile ou un agent pair compromis ne peut ni injecter de confiance, ni contourner la quarantaine, ni donner d'instruction au SA.

---

## Phase 10 — Calibration, benchmark, ouverture P3 (gatée, J10)

**Gate d'entrée** : B1–B4 (§9) levés — gold ≥ 3000 phrases, checkpoint re-mesuré sur un harnais unique, benchmark construit. Aucune échéance calendaire : le gate est mesurable.

#### T10.1 — Benchmark agentique MVP (L)
- **Détail** : 1000 documents CTI avec vérité causale, 200 claims avec verdicts de référence, 50 chaînes avec chemin connu, scénario de flux 24 h avec anomalies injectées ; runner reproductible dans `benchmarks/`.

#### T10.2 — Corpus de calibration dérivé du gold (M)
- **Détail** : ~200 paires claim→verdict (phrase du gold = `CONFIRMED` attendu ; paires croisées sans lien = `UNCONFIRMED` synthétiques tracés) ; **séparation stricte calibration / validation** (les 200 claims manuels du benchmark sont réservés à la validation) ; classe avec N < 30 ⇒ gel (discipline R8/R10).

#### T10.3 — Balayage de calibration (M)
- **Détail** : quorum ∈ {1.5, 2, 2.5, 3} × Nmax ∈ {20, 50, 100} **× noisy-OR en alternative**, métrique précision/rappel ≥ 0.80 / 0.75 ; tableau + choix argumenté ; passage `provisoire → calibré` consigné par ADR.

#### T10.4 — Tests de non-double-pondération (M)
- **Détail** : preuve que score d'arête × fiabilité de source ne compte jamais deux fois la même information (corpus T10.2) ; prérequis de mise en production de l'arbitrage.

#### T10.5 — Mesure des SLO finaux (M)
- **Cibles de conception** : `validate()` p99 < 200 ms (50k) ; `query_causes()` p99 < 50 ms (100k) ; CONFIRMED correct ≥ 0.85 ; faux UNCONFIRMED ≤ 0.10 ; WAL sans perte après crash ; cycle no-op < 10 ms ; 72 h sans fuite mémoire, croissance WAL linéaire.

#### T10.6 — Consommation de modèles (M) — *conditionnée à B2*
- **Détail** : registre de modèles par hash, chargement paresseux unique par hash ; contrat de modèle-outil (`score_candidates`, `propose_alias`) avec tests de contrat ; transcription stricte (schéma validé, rejet + log, jamais de défaut silencieux, contrôle de portée) ; manifeste de ce que le modèle a vu ; protocole pickle CodeBERT (§17.5) exécuté hors poste de développement, prod = `safetensors` + `weights_only=True`.

#### T10.7 — Gate d'ouverture P3 (S)
- **Checklist mesurable** : benchmark construit et vert ; `can()` testé en adversarial ; budgets calibrés sur ≥ 100 cycles ; quarantaine prouvée en dogfood. Seulement après : `delegate`, index sémantique, déduplication sémantique, chargement à chaud.

#### T10.8 — Conversation (flux F7) (L) — *optionnel, gaté*
- **Détail** : `respond()` branché comme sortie unifiée (`ToolResult` côté machine, texte verbalisé côté humain) ; `pending` de clarification persisté et repris au démarrage ; poids 0.5 pour les questions ingérées au mieux.

---

## 8. Stratégie de tests et de CI

| Couche | Outil | Ce qu'elle prouve | Phase |
|---|---|---|---|
| Unitaire | pytest | Logique pure (politique, arbitrage, alias, conditions) | toutes |
| Contrat | pytest + plugins factices | Tout plugin respecte `harness/1.0` ; le noyau n'est pas modifié pour en ajouter un | 1+ |
| Propriétés | hypothesis | Rejeu WAL ≡ état ; index ≡ scan ; cache ≡ sans cache | 2, 5 |
| Fautes | sous-processus + `kill -9`, injection à chaque étape | Aucune perte, compaction atomique | 2, 4 |
| Adversarial | corpus figé + suite `can()` | Injection, provenance forgée, escalade de permissions | 1, 9 |
| Hors ligne | `pytest --disable-socket` | Noyau et dogfood sans réseau (I10) | 3+ |
| Benchmarks | pytest-benchmark | SLO de latence mesurés, jamais supposés | 2, 5, 8 |
| Charge | script 72 h | Pas de fuite, croissance WAL linéaire | 7, 10 |
| Architecture | import-linter + SLOC | I1, I2 en continu | 0+ |

Règles : toute valeur `provisoire` a un test qui la lit depuis la configuration ; aucun SLO n'est affiché comme atteint tant qu'un rapport daté ne l'a pas mesuré ; un test d'acceptation de phase ne se contourne pas par une exception « temporaire ».

## 9. Bloquants et risques

### 9.1 Bloquants côté moteur (§29 de l'étude)

| # | Bloquant | Conséquence pour le plan |
|---|---|---|
| B1 | Confiances du moteur non calibrées (ECE 0.33–0.55) | Toute `conf` est traitée comme non calibrée : plafonds par canal (T9.1), constantes `provisoires`, `EN RÉVISION` par défaut |
| B2 | Checkpoint non re-mesuré (`val_edge_f1` contradictoire) | Registre de modèles vide ; aucun modèle consommé avant re-mesure (T10.6) |
| B3 | Gold actuel : 219 phrases, gel R8/R10 | Phases 0–9 n'en dépendent pas ; T10.2–T10.3 attendent gold-3000 |
| B4 | Benchmarks et SLO inexistants | T10.1 ; entrée en P3 conditionnée par un benchmark vert |

### 9.2 Risques d'exécution

| Risque | Signal d'alerte | Mitigation |
|---|---|---|
| Accès Python à `CYCLES`/`GAPS` indisponible | T5.4 aboutit à « CLI seul » | ADR + wrapper `subprocess` isolé, liste blanche amendée |
| Dérive du noyau au-delà de 500 SLOC | Test SLOC rouge | Refuser la PR ; revoir le design du plugin (§13.6) |
| Corruption du WAL | `crc_failed`/`seq_gap` > 0 au démarrage | Repli `.prev`, rapport par phase, tests de fautes |
| Incohérence API ↔ scheduler | Mutation hors thread propriétaire | File d'événements unique, test de charge T8.1 |
| Dérive de version du moteur | Test de fumée rouge | Version pinnée, `docs/engine-compat.md`, test de fumée en CI |
| Constantes figées trop tôt | Nombre littéral dans le code | Lint I9 ; tout ce qui dépend de B3/B4 reste `provisoire` |
| Glissement de périmètre | Travail sur `delegate`/sémantique avant J10 | Garde de directive (`delegate: disabled`, `semantic_index_min_edges`) |
| Coût de chargement des modèles (~25 s, ~1 Go) | Démarrage lent | Chargement paresseux par hash, un seul chargement par hash |

## 10. Charge indicative et chemin critique

| Phase | Charge (j-h) | Phase | Charge (j-h) |
|---|---|---|---|
| 0 | 4,5 | 5 | 14 |
| 1 | 12,5 | 6 | 11,5 |
| 2 | 12,5 | 7 | 6 |
| 3 | 14,5 | 8 | 12 |
| 4 | 13,5 | 9 | 15 |
| **Total 0–9** | **≈ 116 j-h** | 10 | gatée (hors total) |

Barème S = 0,5 j, M = 1,5 j, L = 4 j ; **provisoire**, à recaler après J2 sur la vélocité observée. À temps partiel, compter 2 à 3 fois la durée calendaire.

**Chemin critique** : T0.1 → T0.2 → T1.1 → T1.3 → T1.5 → T2.1 → T2.2 → T3.1 → T3.2 → T3.6 → T3.8 → T4.4 → T4.5 → T5.3 → T8.1. La phase 6 (arbitrage) et la phase 9 (sécurité) sont parallélisables avec 7 et 8 si les jalons J5 et J4 sont verts.

## 11. Définition de « terminé » et décisions ouvertes

### 11.1 Une tâche est terminée quand

1. ses critères d'acceptation sont des tests verts en CI (pas une vérification manuelle) ;
2. ruff, mypy et les gardes I1/I2 sont verts ;
3. toute nouvelle valeur numérique est soit justifiée par une mesure, soit marquée `provisoire` en configuration ;
4. toute décision d'architecture nouvelle a son ADR ;
5. aucune sortie causale n'a perdu sa provenance (I4).

### 11.2 Décisions à trancher par ADR en cours de route

| Décision | Avant la tâche |
|---|---|
| Nom exact du module d'import du moteur | T0.2 |
| Chemin d'accès à `CYCLES`/`GAPS`/`PROVENANCE`/`RELIABILITY` (binding ou CLI Rust) | T5.4 |
| Règle d'opposition pour `CONTRADICTED` (relations incompatibles, négation) | T5.3 |
| Verbalisation humaine : gabarits SA ou ajout du verbaliseur moteur à la liste blanche | T5.7 |
| Jeton d'API : génération, stockage, rotation | T8.3 |
| Politique de batch `fsync` (nombre de lignes / délai) | T2.1 |
