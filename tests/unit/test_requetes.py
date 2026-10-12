# Copyright 2026 Michel Tendeng
# SPDX-License-Identifier: Apache-2.0
"""T5.1 — requêtes : résolution 4 niveaux, I4 100 %, vide, manifestes."""

from __future__ import annotations

import tempfile
from pathlib import Path

from evidra.kernel.contracts import Context, Status, Tool
from evidra.kernel.manifest import manifest_from_plugin
from evidra.memory.envelope import CirCore, Provenance
from evidra.memory.memoire import Memoire
from evidra.memory.store import Magasin
from evidra.tools.query_causes import OutilCauses
from evidra.tools.query_effects import OutilEffets


def _noyau(src: str, dst: str, ref: str = "doc://1", conf: float = 0.87) -> CirCore:
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
        _noyau("Surchauffe du moteur", "panne de pompe", "doc://1"),
        channel="test",
        fiabilite=0.9,
        horodatage="t1",
    )
    memo.observer(
        _noyau("Surchauffe du moteur", "alerte température", "doc://2"),
        channel="test",
        fiabilite=0.5,
        horodatage="t2",
    )
    return memo


def _ctx() -> Context:
    magasin = Magasin(Path(tempfile.mkdtemp()))
    return Context(store=magasin, domain="code")


def test_conformes_protocole_et_manifeste() -> None:
    assert isinstance(OutilCauses({}), Tool) and isinstance(OutilEffets({}), Tool)
    assert manifest_from_plugin(OutilCauses).name == "query_causes"
    assert manifest_from_plugin(OutilEffets).name == "query_effects"


def test_causes_exactes_provenance_complete() -> None:
    recu = OutilCauses({"code": _memoire()}).run(_ctx(), {"concept": "panne de pompe"})
    assert recu.status is Status.OK
    assert len(recu.payload["reponses"]) == 1
    assert recu.payload["resolution"] == "exacte"
    (preuve,) = recu.payload["reponses"]
    assert preuve["source"] == "Surchauffe du moteur"
    assert preuve["confiance"] == 0.87 and preuve["statut"] == "nouvelle"
    assert preuve["fiabilite_source"] == 0.9
    prov = preuve["provenance"]
    assert prov["ref"] == "doc://1"
    assert set(prov) >= {"ref", "span", "extraction_method", "model_version", "extracted_at"}


def test_effets_miroir() -> None:
    recu = OutilEffets({"code": _memoire()}).run(_ctx(), {"concept": "Surchauffe du moteur"})
    assert recu.status is Status.OK and len(recu.payload["reponses"]) == 2
    assert recu.payload["resolution"] == "exacte"


def test_repli_tokens_puis_sous_chaine() -> None:
    memo = _memoire()
    ctx = _ctx()
    recu = OutilCauses({"code": memo}).run(ctx, {"concept": "pompe"})
    assert recu.payload["resolution"] == "tokens" and len(recu.payload["reponses"]) == 1
    recu = OutilCauses({"code": memo}).run(ctx, {"concept": "urchauf"})
    assert recu.payload["resolution"] == "sous-chaine" and len(recu.payload["reponses"]) == 2


def test_vide_jamais_negatif() -> None:
    recu = OutilCauses({"code": _memoire()}).run(_ctx(), {"concept": "xyz introuvable"})
    assert recu.status is Status.OK
    assert recu.payload["reponses"] == [] and recu.payload["resolution"] == "vide"
    assert recu.payload["note"] == "aucune source"


def test_invalides() -> None:
    outil = OutilCauses({"code": _memoire()})
    assert outil.run(_ctx(), {"concept": ""}).status is Status.FAILED
    assert outil.run(_ctx(), {"concept": 42}).status is Status.FAILED
    assert OutilCauses({"code": _memoire()}).run(_ctx(), "pas-un-dict").status is Status.FAILED
    assert (
        OutilEffets({}).run(Context(store=_ctx().store, domain="inconnu"), {"concept": "x"}).status
        is Status.FAILED
    )
