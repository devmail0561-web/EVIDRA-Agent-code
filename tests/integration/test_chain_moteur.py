# Copyright 2026 Michel Tendeng
# SPDX-License-Identifier: Apache-2.0
"""T5.2 — acceptation Dijkstra : 3×0.90 bat le direct 0.60 (binaire frais)."""

# ruff: noqa: E402 — binaire requis, skip explicite sinon
from __future__ import annotations

import shutil
import tempfile
from pathlib import Path

import pytest

from evidra.engine_bridge.binaire import trouver_binaire
from evidra.kernel.contracts import Context, Status
from evidra.memory.envelope import CirCore, Provenance
from evidra.memory.memoire import Memoire
from evidra.memory.store import Magasin
from evidra.tools.query_chain import OutilChaine

BINAIRE = trouver_binaire() or shutil.which("gcn")
pytestmark = pytest.mark.skipif(BINAIRE is None, reason="binaire gcn requis (Dijkstra Rust)")


def _noyau(src: str, dst: str, conf: float, ref: str) -> CirCore:
    return CirCore(
        source=src,
        target=dst,
        relation="cause",
        confidence=conf,
        provenance=Provenance(
            ref=ref,
            span="synthetic",
            extraction_method="symbolic_rust",
            model_version="v",
            extracted_at="t",
        ),
    )


def test_3x090_bat_direct_060() -> None:
    memo = Memoire("code")
    memo.observer(
        _noyau("Alpha", "Beta", 0.90, "doc://1"), channel="test", fiabilite=0.9, horodatage="t1"
    )
    memo.observer(
        _noyau("Beta", "Gamma", 0.90, "doc://2"), channel="test", fiabilite=0.9, horodatage="t2"
    )
    memo.observer(
        _noyau("Gamma", "Delta", 0.90, "doc://3"), channel="test", fiabilite=0.9, horodatage="t3"
    )
    memo.observer(
        _noyau("Alpha", "Delta", 0.60, "doc://4"), channel="test", fiabilite=0.9, horodatage="t4"
    )
    ctx = Context(store=Magasin(Path(tempfile.mkdtemp())), domain="code")
    recu = OutilChaine({"code": memo}).run(ctx, {"de": "Alpha", "vers": "Delta"})
    assert recu.status is Status.OK
    chemin = recu.payload["chemin"]
    assert chemin["noeuds"] == ["Alpha", "Beta", "Gamma", "Delta"]
    assert abs(chemin["confiance"] - 0.729) < 1e-6
    assert [p["provenance"]["ref"] for p in chemin["preuves"]] == ["doc://1", "doc://2", "doc://3"]
