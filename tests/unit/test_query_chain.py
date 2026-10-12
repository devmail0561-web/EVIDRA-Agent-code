# Copyright 2026 Michel Tendeng
# SPDX-License-Identifier: Apache-2.0
"""T5.2 — chaîne : découpe, preuves jointes, degrade explicite, contrat."""

from __future__ import annotations

import tempfile
from pathlib import Path

from evidra.kernel.contracts import Context, Status, Tool
from evidra.kernel.manifest import manifest_from_plugin
from evidra.memory.envelope import CirCore, Provenance
from evidra.memory.memoire import Memoire
from evidra.memory.store import Magasin
from evidra.tools.query_chain import OutilChaine


def _noyau(src: str, dst: str, ref: str = "doc://1", conf: float = 0.9) -> CirCore:
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


def _memoire() -> Memoire:
    memo = Memoire("code")
    memo.observer(
        _noyau("Alpha", "Beta", "doc://1"), channel="test", fiabilite=0.9, horodatage="t1"
    )
    memo.observer(
        _noyau("Beta", "Gamma", "doc://2"), channel="test", fiabilite=0.9, horodatage="t2"
    )
    memo.observer(
        _noyau("Gamma", "Delta", "doc://3"), channel="test", fiabilite=0.9, horodatage="t3"
    )
    memo.observer(
        _noyau("Alpha", "Delta", "doc://4", conf=0.6),
        channel="test",
        fiabilite=0.9,
        horodatage="t4",
    )
    return memo


def _ctx() -> Context:
    return Context(store=Magasin(Path(tempfile.mkdtemp())), domain="code")


def _faux_interroger(binaire, iri, de, vers, *, timeout_s=30.0):
    assert isinstance(binaire, str) and iri["edges"] and timeout_s > 0
    return {
        "found": True,
        "links": [
            {"from": "Alpha", "to": "Beta", "relation": "cause", "confidence": 0.9},
            {"from": "Beta", "to": "Gamma", "relation": "cause", "confidence": 0.9},
            {"from": "Gamma", "to": "Delta", "relation": "cause", "confidence": 0.9},
        ],
    }


def test_conforme_et_manifeste() -> None:
    assert isinstance(OutilChaine({}), Tool)
    assert manifest_from_plugin(OutilChaine).name == "query_chain"


def test_chaine_preuves_provenance() -> None:
    outil = OutilChaine({"code": _memoire()}, interroger=_faux_interroger)
    recu = outil.run(_ctx(), {"de": "Alpha", "vers": "Delta"})
    assert recu.status is Status.OK
    assert recu.payload["trouve"] is True
    chemin = recu.payload["chemin"]
    assert chemin["noeuds"] == ["Alpha", "Beta", "Gamma", "Delta"]
    assert abs(chemin["confiance"] - 0.729) < 1e-6  # produit brut moteur
    assert [p["provenance"]["ref"] for p in chemin["preuves"]] == ["doc://1", "doc://2", "doc://3"]
    assert recu.payload["tronque"] == 0
    assert recu.payload["derives"] == []  # aucune synthèse SA (T6.6 gatée)


def test_non_trouve_degrade() -> None:
    def _vide(binaire, iri, de, vers, *, timeout_s=30.0):
        return {"found": False, "links": []}

    recu = OutilChaine({"code": _memoire()}, interroger=_vide).run(
        _ctx(), {"de": "Alpha", "vers": "ZZZ"}
    )
    assert recu.status is Status.DEGRADE
    assert recu.payload["trouve"] is False


def test_rust_indisponible_degrade_explicite() -> None:
    from evidra.engine_bridge.rust import RustIndisponible

    def _panne(binaire, iri, de, vers, *, timeout_s=30.0):
        raise RustIndisponible("binaire absent")

    recu = OutilChaine({"code": _memoire()}, interroger=_panne).run(
        _ctx(), {"de": "Alpha", "vers": "Delta"}
    )
    assert recu.status is Status.DEGRADE
    assert "indisponible" in recu.payload["motif"]


def test_invalides() -> None:
    outil = OutilChaine({"code": _memoire()}, interroger=_faux_interroger)
    assert outil.run(_ctx(), {"de": "", "vers": "x"}).status is Status.FAILED
    assert outil.run(_ctx(), {"de": "a"}).status is Status.FAILED
    assert outil.run(_ctx(), {"de": "a", "vers": "b", "profondeur": 0}).status is Status.FAILED
    assert (
        outil.run(Context(store=_ctx().store, domain="inconnu"), {"de": "a", "vers": "b"}).status
        is Status.FAILED
    )
