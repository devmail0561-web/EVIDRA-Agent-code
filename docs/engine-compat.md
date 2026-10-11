# Compatibilité moteur (T0.2)

## Moteur consommé

| Champ | Valeur constatée le 2026-10-11 |
|---|---|
| Sources | `../projet_CNM/gcn-python` (dépendance `path` éditable du `pyproject.toml`) |
| Version package | `gcn-python 4.0.0` (`__version__`) |
| Commit workspace | `20163daea57c0da065e22aa2cdb179ab69ba194a` |
| Branche workspace | `refacto/arch-cible-refacto-2026-10` (109 commits devant `master`, non mergée) |
| Python | 3.11.9 (moteur exige ≥ 3.10, SA exige ≥ 3.11) |

## Surface d'import résolue (liste blanche I1)

| Symbole | Chemin constaté |
|---|---|
| `GCNEngine` (+ `analyze`, `analyze_batch`) | `gcn_python.engine` (exporté au top-level) |
| `reason`, `reason_question`, `verify_path` | `gcn_python.reasoning.engine` |
| `CausalGraph` | `gcn_python.verbalizer.instructions` (classe) ; `gcn_python.layer3.interface` (Protocol) |
| ⚠ `analyze` (fonction, clauses/connecteurs) | `gcn_python.layer0.engine_b` — **hors liste blanche** (segmentation, pas des CIR) : ne pas importer |
| ⚠ `GCNEngine` (classe) | **Point ouvert** : la liste blanche I1 nomme les méthodes `analyze`/`analyze_batch`, mais leur seul accès passe par l'instance `GCNEngine` — l'import de la classe par `engine_bridge` (construction) est inévitable. Garde T0.4 appliquée à la lettre en attendant l'ADR qui tranchera (autoriser `GCNEngine` en construction seule vs fabrique moteur). Voir ADR-0010. |

## Comportements prouvés par `tests/integration/test_engine_smoke.py`

- Pipeline minimal sans checkpoint ni `gcn-cli` : `analyze` FR + EN → CIR `dict`
  (`source_text`, `nodes`, `edges`), ≥ 1 arête, provenance à 5 clés
  (`ref`, `span`, `extraction_method`, `model_version`, `extracted_at`).
- Provenance Python constatée : `ref=None`, `span` marqueur (`"synthetic"`),
  `extraction_method="ml_python"` — enveloppement SA requis (T3.2).
- `analyze_batch` : dédup par lots (M1b), blancs sautés, copies indépendantes.

## Écarts provisoires

- `uv sync` **bloqué** : réseau indisponible pour télécharger les roues
  (`numpy` absent du cache) — en attente. En attendant, les tests utilisent le
  Python système (pytest 9.1.1, filelock, pydantic 2.13.5 présents) avec
  `sys.path` injecté par `tests/conftest.py` (`GCN_PYTHON_SRC` ou défaut
  relatif). Le `pip install`é système `gcn_python` 2.5.0 est **masqué** par
  cette injection (source 4.0.0 prioritaire).
- `gcn-cli` (binaire Rust) **absent** (`NO-GCN-BIN`) : le smoke test utilise un
  parseur stub ; les chemins `CYCLES`/`GAPS` via CLI restent à trancher (T5.4).
- Chemin `uv.sources` : `../projet_CNM/gcn-python` (le plan suppose un workspace
  `evidra/` voisin de `gcn-python/` ; ici le dépôt `harness-gcn/` est voisin de
  `projet_CNM/`).
- **Branches non mergées** : le pin porte sur une branche refacto non mergée
  (109 commits devant `master`). Tant que le SHA existe, la CI (`ref: <sha>`),
  le `uv.lock` et l'éditable local restent reproductibles. Risque : réécriture
  (rebase) de la branche → SHA introuvable → `uv sync` et CI rouges (signal
  explicite, pas de corruption silencieuse). Ancre stable prévue : première
  release du moteur (cf. ADR-0001).
- Gold-219 : somme des classes de `accuracy_gold219.json` (219), `gold_mini.jsonl`
  = 85 phrases — le fichier source des 219 phrases reste à localiser (risque
  signalé pour T3.9).
