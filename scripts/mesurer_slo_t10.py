#!/usr/bin/env python3
# Copyright 2026 Michel Tendeng
# SPDX-License-Identifier: Apache-2.0
"""Banc SLO T10.5 partiel : latences et système mesurables sans gold.

Cibles de conception (PLAN_SA T10.5) : `validate()` p99 < 200 ms (50k),
`query_causes()` p99 < 50 ms (100k), cycle no-op < 10 ms. Les métriques
CONFIRMED (≥ 0.85) et faux UNCONFIRMED (≤ 0.10) exigent le gold-3000 (B3,
toujours bloqué) et sont marquées `non_mesurees`. WAL sans perte et charge
72 h relèvent des suites dédiées (`tests/fault/`, `scripts/charge_72h.py`,
lancées en CI, pas ici).
Sortie : objet JSON daté sur stdout, écrit dans `--sortie` si fourni.
"""

from __future__ import annotations

import argparse
import json
import sys
import tempfile
import time
from datetime import UTC, datetime
from pathlib import Path

RACINE = Path(__file__).resolve().parent.parent

sys.path.insert(0, str(RACINE / "src"))
sys.path.insert(0, str(RACINE))

from evidra.kernel.contracts import Context  # noqa: E402
from evidra.kernel.scheduler import Scheduler  # noqa: E402
from evidra.memory.envelope import CirCore, Provenance  # noqa: E402
from evidra.memory.memoire import Memoire  # noqa: E402
from evidra.memory.store import Magasin  # noqa: E402
from evidra.tools.query_causes import OutilCauses  # noqa: E402
from evidra.tools.validate import OutilValider  # noqa: E402
from tests.bench.synthetique import requetes  # noqa: E402


def _p99(durees_ms: list[float]) -> float:
    triees = sorted(durees_ms)
    return triees[max(0, int(len(triees) * 0.99) - 1)] if triees else 0.0


def mesurer_validate_p99(n: int = 50_000, echantillons: int = 100) -> dict[str, float]:
    """p99 `validate()` sur n arêtes (triplets directs, verdicts CONFIRMED)."""
    memo = Memoire("bench")
    for i in range(n):
        memo.observer(
            CirCore(
                source=f"cause-{i:05d}",
                target=f"effet-{i:05d}",
                relation="cause",
                confidence=0.8,
                provenance=Provenance(
                    ref="doc://bench",
                    span="synthetic",
                    extraction_method="ml_python",
                    model_version="v",
                    extracted_at="t",
                ),
            ),
            channel="bench",
            fiabilite=0.5,
            horodatage="t",
        )
    outil = OutilValider({"bench": memo})
    with Magasin(Path(tempfile.mkdtemp()) / "b") as magasin:
        ctx = Context(store=magasin, domain="bench")
        durees = []
        pas = max(1, n // echantillons)
        for i in range(0, n, pas):
            debut = time.perf_counter()
            recu = outil.run(
                ctx,
                {
                    "claim": {
                        "source": f"cause-{i:05d}",
                        "relation": "cause",
                        "cible": f"effet-{i:05d}",
                    }
                },
            )
            durees.append((time.perf_counter() - debut) * 1000.0)
            assert recu.payload["verdict"] == "CONFIRMED"
    return {"p99_ms": round(_p99(durees), 3), "n": float(n), "echantillons": float(len(durees))}


def mesurer_causes_p99(n: int = 100_000) -> dict[str, float]:
    """p99 `query_causes()` sur n arêtes."""
    memo = Memoire("bench")
    for i in range(n):
        memo.observer(
            CirCore(
                source=f"concept-{i % 5000:04d}",
                target=f"feuille-{i:06d}",
                relation="cause",
                confidence=0.8,
                provenance=Provenance(
                    ref=f"doc://{i % 100}",
                    span="synthetic",
                    extraction_method="ml_python",
                    model_version="v",
                    extracted_at="t",
                ),
            ),
            channel="bench",
            fiabilite=0.5,
            horodatage="t",
        )
    outil = OutilCauses({"bench": memo})
    with Magasin(Path(tempfile.mkdtemp()) / "b") as magasin:
        ctx = Context(store=magasin, domain="bench")
        durees = []
        for requete in requetes():
            debut = time.perf_counter()
            outil.run(ctx, {"concept": requete})
            durees.append((time.perf_counter() - debut) * 1000.0)
    return {"p99_ms": round(_p99(durees), 3), "n": float(n), "echantillons": float(len(durees))}


def mesurer_noop_ms(ticks: int = 50) -> dict[str, float]:
    """Cycle no-op (scheduler nu, sans condition) : médiane et max, ms."""
    ordonnanceur = Scheduler()
    durees = []
    for _ in range(ticks):
        debut = time.perf_counter()
        ordonnanceur.tour()
        durees.append((time.perf_counter() - debut) * 1000.0)
    triees = sorted(durees)
    return {
        "mediane_ms": round(triees[len(triees) // 2], 3),
        "max_ms": round(triees[-1], 3),
        "ticks": float(ticks),
    }


def main() -> None:
    args = argparse.ArgumentParser()
    args.add_argument("--sortie", default="")
    opts = args.parse_args()
    rapport = {
        "date": datetime.now(UTC).isoformat(),
        "validate_p99_50k": mesurer_validate_p99(),
        "causes_p99_100k": mesurer_causes_p99(),
        "cycle_noop": mesurer_noop_ms(),
        "confirmed_correct_ge_085": "non_mesure (gold-3000 B3 bloqué)",
        "faux_unconfirmed_le_010": "non_mesure (gold-3000 B3 bloqué)",
        "wal_sans_perte": "suite tests/fault/test_wal_crash.py (CI)",
        "charge_72h": "protocole scripts/charge_72h.py (fumé 2 s en CI)",
    }
    texte = json.dumps(rapport, indent=2, ensure_ascii=False)
    print(texte)
    if opts.sortie:
        Path(opts.sortie).write_text(texte + "\n", encoding="utf-8")


if __name__ == "__main__":
    sys.exit(main())
