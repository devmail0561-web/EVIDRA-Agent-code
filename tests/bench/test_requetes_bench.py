# Copyright 2026 Michel Tendeng
# SPDX-License-Identifier: Apache-2.0
"""T5.1 — SLO : requêtes bout-en-bout p99 < 50 ms sur 100 000 arêtes (SLO P1)."""

from __future__ import annotations

import tempfile
import time
from pathlib import Path

from evidra.kernel.contracts import Context, Status
from evidra.memory.envelope import CirCore, Provenance
from evidra.memory.memoire import Memoire
from evidra.memory.store import Magasin
from evidra.tools.query_causes import OutilCauses
from tests.bench.synthetique import requetes


def _memoire_100k() -> Memoire:
    memo = Memoire("bench")
    for i in range(100_000):
        src, dst = f"concept-{i % 5000:04d}", f"feuille-{i:06d}"
        noyau = CirCore(
            source=src,
            target=dst,
            relation="cause",
            confidence=0.8,
            provenance=Provenance(
                ref=f"doc://{i % 100}",
                span="synthetic",
                extraction_method="ml_python",
                model_version="v",
                extracted_at="t",
            ),
        )
        memo.observer(noyau, channel="bench", fiabilite=0.5, horodatage="t")
    return memo


def test_slo_requetes_p99_50ms_100k() -> None:
    memo = _memoire_100k()
    assert len(memo.index) == 100_000
    magasin = Magasin(Path(tempfile.mkdtemp()))
    outil = OutilCauses({"bench": memo})
    ctx = Context(store=magasin, domain="bench")
    durees = []
    for requete in requetes():
        debut = time.perf_counter()
        recu = outil.run(ctx, {"concept": requete})
        durees.append((time.perf_counter() - debut) * 1000.0)
        assert recu.status is Status.OK
    magasin.close()
    durees.sort()
    p99 = durees[max(0, int(len(durees) * 0.99) - 1)]
    assert p99 < 50.0, f"p99={p99:.2f} ms sur {len(durees)} requêtes"
