# Evidra — Runbook d'exploitation (T8.6)

## Démarrage

```sh
uv sync --extra api            # API (FastAPI + uvicorn) ; `--extra network` pour les tests API
uv run evidra serve --directive directives/code.dogfood.json --data-dir ./data
```

- Écoute `127.0.0.1:8000` par défaut ; toute autre interface (`--hote`) est un
  choix explicite à tracer (l'exposition externe exige des jetons, ci-dessous).
- `--essai` = moteur non calibré (B1), dev uniquement, jamais en production.
- Santé : `GET /status` (200 + `degraded` éventuel) ; boucle vivante si `ticks` croît.

## Authentification (T8.3)

`directive.api.jetons` (fichier **0600**, jamais commité avec des secrets) :

```json
{"api": {"jetons": [{"nom": "lecteur", "empreinte": "<sha256>", "verbes": ["read"]}],
          "cles_directive": {"owner1": "<secret-hmac>"}}}
```

- Empreinte : `python -c "import hashlib;print(hashlib.sha256(b'<jeton>').hexdigest())"`.
- Sans jeton configuré : routes ouvertes (dev/dogfood uniquement).
- Sans jeton / inconnu ⇒ **401** ; verbe insuffisant ⇒ **403** (tracé).
- `POST /directive` : verbe `modify` **et** `X-Signature: <cle_id>:<hmac>` du JSON
  canonique ; directive invalide ⇒ **422** avant toute écriture ; chaque version
  entre au WAL (`registry/directive`). `POST /directive/rollback` restaure.
- Rotation : remplacer le secret dans `cles_directive`, re-signer, publier.

## Reprise après crash

1. `kill -9` ⇒ les lignes `fsync`ées sont intactes (WAL tolérant par ligne).
2. Redémarrer avec le même `--data-dir` : snapshot + rejeu, `ABANDONED` repris,
   `degraded` motivé si manifeste divergent (harness/moteur changés).
3. `evidra status --data-dir D` (lecture seule, sans verrou) avant/après.

## Compaction

```sh
evidra compact --data-dir D --domaine code   # verrou requis : refuse si l'agent tourne
```

Snapshot + troncation par stream ; `.prev` conservé (repli snapshot corrompu).

## Alertes

`alerts.jsonl` sous `data_dir` (local, toujours) ; `alert_endpoint` = egress
best-effort (hors ligne ⇒ `degrade`, conservée). Acquittement : via registres
(`acquitter_alerte`, motif exigé) — pas d'endpoint avant la phase 10.
