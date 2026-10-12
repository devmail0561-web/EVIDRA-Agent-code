# Copyright 2026 Michel Tendeng
# SPDX-License-Identifier: Apache-2.0
"""T5.5 — cycles/gaps réels : preuves jointes bout-en-bout (binaire frais)."""

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
from evidra.tools.counterfactual import OutilContrefactuel
from evidra.tools.query_cycles import OutilCycles
from evidra.tools.query_gaps import OutilLacunes

BINAIRE = trouver_binaire() or shutil.which("gcn")
pytestmark = pytest.mark.skipif(BINAIRE is None, reason="binaire gcn requis (Tarjan/gaps Rust)")


def _noyau(src: str, dst: str, ref: str) -> CirCore:
    return CirCore(
        source=src,
        target=dst,
        relation="cause",
        confidence=0.8,
        provenance=Provenance(
            ref=ref,
            span="synthetic",
            extraction_method="symbolic_rust",
            model_version="v",
            extracted_at="t",
        ),
    )


def _memoire() -> Memoire:
    memo = Memoire("code")
    memo.observer(
        _noyau("Alpha", "Beta", "doc://1"), channel="test", fiabilite=0.9, horodatage="t1"
    )
    memo.observer(
        _noyau("Beta", "Gamma", "doc://2"), channel="test", fiabilite=0.9, horodatage="t2"
    )
    memo.observer(
        _noyau("Gamma", "Alpha", "doc://3"), channel="test", fiabilite=0.9, horodatage="t3"
    )
    return memo


def _ctx() -> Context:
    return Context(store=Magasin(Path(tempfile.mkdtemp())), domain="code")


def test_cycle_reel_preuves() -> None:
    recu = OutilCycles({"code": _memoire()}).run(_ctx(), {})
    assert recu.status is Status.OK
    assert len(recu.payload["cycles"]) == 1
    (cycle,) = recu.payload["cycles"]
    assert set(cycle["noeuds"]) == {"Alpha", "Beta", "Gamma"}
    assert sorted(p["provenance"]["ref"] for p in cycle["preuves"]) == [
        "doc://1",
        "doc://2",
        "doc://3",
    ]


def test_gaps_reel() -> None:
    recu = OutilLacunes({"code": _memoire()}).run(_ctx(), {"chaine": ["Alpha", "Beta"]})
    assert recu.status is Status.OK
    assert "lacunes" in recu.payload and "tronque" in recu.payload


def test_counterfactual_reel_etiquete() -> None:
    recu = OutilContrefactuel({"code": _memoire()}).run(_ctx(), {"concept": "Alpha"})
    assert recu.status is Status.OK
    assert "sans contrôle de confondeurs" in recu.payload["avertissement"]
    assert any(
        p["provenance"]["ref"].startswith("doc://")
        for e in recu.payload["effets"]
        for p in e["preuves"]
    )
