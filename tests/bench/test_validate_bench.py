# Copyright 2026 Michel Tendeng
# SPDX-License-Identifier: Apache-2.0
"""T5.3 — SLO : `validate()` p99 < 200 ms sur 50k arêtes (SLO P1)."""

from __future__ import annotations

import tempfile
import time
from pathlib import Path

from evidra.kernel.contracts import Context
from evidra.memory.envelope import CirCore, Provenance
from evidra.memory.memoire import Memoire
from evidra.memory.store import Magasin
from evidra.tools.validate import OutilValider


def test_slo_validate_p99_200ms_50k() -> None:
    memo = Memoire("bench")
    for i in range(50_000):
        noyau = CirCore(
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
        )
        memo.observer(noyau, channel="bench", fiabilite=0.5, horodatage="t")
    outil = OutilValider({"bench": memo})
    ctx = Context(store=Magasin(Path(tempfile.mkdtemp())), domain="bench")
    durees = []
    for i in range(0, 50_000, 500):
        debut = time.perf_counter()
        recu = outil.run(
            ctx,
            {"claim": {"source": f"cause-{i:05d}", "relation": "cause", "cible": f"effet-{i:05d}"}},
        )
        durees.append((time.perf_counter() - debut) * 1000.0)
        assert recu.payload["verdict"] == "CONFIRMED"
    ctx.store.close()
    durees.sort()
    p99 = durees[max(0, int(len(durees) * 0.99) - 1)]
    assert p99 < 200.0, f"p99={p99:.2f} ms sur {len(durees)} verdicts"
