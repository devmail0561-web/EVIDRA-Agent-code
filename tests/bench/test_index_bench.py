# Copyright 2026 Michel Tendeng
# SPDX-License-Identifier: Apache-2.0
"""T2.5 — SLO : `find_causes` p99 < 50 ms sur 100 000 arêtes (SLO P1)."""

from __future__ import annotations

import time

from tests.bench.synthetique import construire, requetes


def test_slo_find_causes_p99_50ms_100k() -> None:
    index = construire(100_000)
    assert len(index) == 100_000
    durees = []
    for requete in requetes():
        debut = time.perf_counter()
        index.causes(requete)
        durees.append((time.perf_counter() - debut) * 1000.0)
    durees.sort()
    p99 = durees[max(0, int(len(durees) * 0.99) - 1)]
    assert p99 < 50.0, f"p99={p99:.2f} ms sur {len(durees)} requêtes"
