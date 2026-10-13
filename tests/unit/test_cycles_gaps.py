# Copyright 2026 Michel Tendeng
# SPDX-License-Identifier: Apache-2.0
"""T5.5 — cycles/gaps/counterfactual : preuves jointes, vide OK, sans écrit."""

from __future__ import annotations

import sys
import tempfile
from pathlib import Path

import pytest

from evidra.kernel.contracts import Context, Status, Tool
from evidra.kernel.manifest import manifest_from_plugin
from evidra.memory.envelope import CirCore, Provenance
from evidra.memory.memoire import Memoire
from evidra.memory.store import Magasin
from evidra.tools.counterfactual import AVERTISSEMENT, OutilContrefactuel
from evidra.tools.query_cycles import OutilCycles
from evidra.tools.query_gaps import OutilLacunes


@pytest.fixture(autouse=True)
def _binaire_gcn_present(monkeypatch: pytest.MonkeyPatch) -> None:
    """Requêtes Rust : `gcn` résolu (production) — le fake reçoit un chemin réel."""
    monkeypatch.setenv("GCN_BIN", sys.executable)


def _noyau(src: str, dst: str, ref: str = "doc://1") -> CirCore:
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


def test_conformes_et_manifestes() -> None:
    for cls, nom in (
        (OutilCycles, "query_cycles"),
        (OutilLacunes, "query_gaps"),
        (OutilContrefactuel, "counterfactual"),
    ):
        assert isinstance(cls({}), Tool)
        assert manifest_from_plugin(cls).name == nom


def test_cycles_preuves() -> None:
    def _faux(binaire, iri, requete, *, timeout_s=30.0):
        assert requete == "CYCLES?" and iri["edges"]
        return {
            "cycles": [
                {
                    "id": 0,
                    "kind": "feedback_positive",
                    "nodes": ["Gamma", "Beta", "Alpha"],
                    "effect": "amplifying",
                }
            ]
        }

    recu = OutilCycles({"code": _memoire()}, interroger=_faux).run(_ctx(), {})
    assert recu.status is Status.OK
    (cycle,) = recu.payload["cycles"]
    assert cycle["noeuds"] == ["Gamma", "Beta", "Alpha"]
    assert cycle["espece"] == "feedback_positive"
    assert sorted(p["provenance"]["ref"] for p in cycle["preuves"]) == [
        "doc://1",
        "doc://2",
        "doc://3",
    ]
    assert cycle["preuves_manquantes"] == 0


def test_cycles_vide_ok() -> None:
    def _faux_vide(binaire, iri, requete, *, timeout_s=30.0):
        return {"cycles": []}

    recu = OutilCycles({"code": _memoire()}, interroger=_faux_vide).run(_ctx(), {})
    assert recu.status is Status.OK and recu.payload["cycles"] == []


def test_gaps_chaine_requise() -> None:
    assert OutilLacunes({"code": _memoire()}).run(_ctx(), {}).status is Status.FAILED
    assert OutilLacunes({"code": _memoire()}).run(_ctx(), {"chaine": []}).status is Status.FAILED


def test_gaps_preuves() -> None:
    def _faux(binaire, iri, requete, *, timeout_s=30.0):
        assert requete == "GAPS?"
        return {
            "gap_edges": [{"from": "Alpha", "to": "Gamma", "relation": "cause"}],
            "unresolved_nodes": 0,
        }

    recu = OutilLacunes({"code": _memoire()}, interroger=_faux).run(
        _ctx(), {"chaine": ["Alpha", "Beta"]}
    )
    assert recu.status is Status.OK
    (lacune,) = recu.payload["lacunes"]
    assert (lacune["de"], lacune["vers"]) == ("Alpha", "Gamma")
    assert (
        lacune["preuves"] == [] and lacune["preuves_manquantes"] == 1
    )  # pas d'arête directe : honnête
    assert recu.payload["noeuds_non_resolus"] == 0


def test_counterfactual_etiquete() -> None:
    def _faux(binaire, iri, requete, *, timeout_s=30.0):
        assert requete.startswith("COUNTERFACTUAL ")
        return {
            "target": "Alpha",
            "actual_effects": [
                {"from": "Alpha", "to": "Beta", "relation": "cause", "confidence": 0.8}
            ],
            "unique_effects": ["Beta"],
        }

    recu = OutilContrefactuel({"code": _memoire()}, interroger=_faux).run(
        _ctx(), {"concept": "Alpha"}
    )
    assert recu.status is Status.OK
    assert recu.payload["avertissement"] == AVERTISSEMENT
    assert (
        "jamais" in recu.payload["avertissement"] and "confondeurs" in recu.payload["avertissement"]
    )
    (effet,) = recu.payload["effets"]
    assert effet["cible"] == "Beta" and effet["preuves"][0]["provenance"]["ref"] == "doc://1"
    assert recu.payload["uniques"] == ["Beta"]


def test_sans_ecrit_ni_binaire() -> None:
    from evidra.engine_bridge.rust import RustIndisponible

    def _panne(binaire, iri, requete, *, timeout_s=30.0):
        raise RustIndisponible("absent")

    memo = _memoire()
    avant = (len(memo.entites), len(memo.index))
    assert OutilCycles({"code": memo}, interroger=_panne).run(_ctx(), {}).status is Status.DEGRADE
    assert (
        OutilLacunes({"code": memo}, interroger=_panne).run(_ctx(), {"chaine": ["Alpha"]}).status
        is Status.DEGRADE
    )
    assert (
        OutilContrefactuel({"code": memo}, interroger=_panne)
        .run(_ctx(), {"concept": "Alpha"})
        .status
        is Status.DEGRADE
    )
    assert (len(memo.entites), len(memo.index)) == avant  # lecture seule prouvée
    assert OutilContrefactuel({"code": memo}).run(_ctx(), {"concept": ""}).status is Status.FAILED
