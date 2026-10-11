# Copyright 2026 Michel Tendeng
# SPDX-License-Identifier: Apache-2.0
"""T2.5 — SLO : `find_causes` p99 < 50 ms sur 100 000 arêtes (SLO P1)."""

from __future__ import annotations

import random
import time

from evidra.memory.index import Index

CONCEPTS = [f"concept-{i:04d}" for i in range(5000)]
MOTS_VARIANTS = ["auth", "login", "panne", "cve", "patch", "serveur"]


def _construire(n: int = 100_000, graine: int = 7) -> Index:
    hasard = random.Random(graine)
    index = Index()
    for i in range(n):
        src = hasard.choice(CONCEPTS)
        if hasard.random() < 0.05:
            src = f"{src} {hasard.choice(MOTS_VARIANTS)}"
        dst = hasard.choice(CONCEPTS)
        index.ajouter(f"e{i:06d}", src, dst, hasard.choice(["causes", "prevents"]), hasard.random())
    return index


def test_slo_find_causes_p99_50ms_100k() -> None:
    index = _construire()
    assert len(index) == 100_000
    requetes = [f"concept-{i:04d}" for i in range(0, 5000, 25)]
    durees = []
    for requete in requetes:
        debut = time.perf_counter()
        index.causes(requete)
        durees.append((time.perf_counter() - debut) * 1000.0)
    durees.sort()
    p99 = durees[max(0, int(len(durees) * 0.99) - 1)]
    assert p99 < 50.0, f"p99={p99:.2f} ms sur {len(durees)} requêtes"
