# Copyright 2026 Michel Tendeng
# SPDX-License-Identifier: Apache-2.0
"""T5.3 — validate : 3 verdicts, table opposés, négation, quarantaine, texte."""

from __future__ import annotations

import tempfile
from pathlib import Path

from evidra.kernel.contracts import Context, Status, Tool, ToolResult
from evidra.kernel.manifest import manifest_from_plugin
from evidra.memory.envelope import CirCore, Provenance
from evidra.memory.memoire import Memoire
from evidra.memory.store import Magasin
from evidra.tools.validate import OutilValider


def _noyau(
    src: str,
    dst: str,
    rel: str = "cause",
    ref: str = "doc://1",
    conf: float = 0.8,
    negated: bool = False,
) -> CirCore:
    return CirCore(
        source=src,
        target=dst,
        relation=rel,
        confidence=conf,
        provenance=Provenance(
            ref=ref,
            span="synthetic",
            extraction_method="symbolic_rust",
            model_version="v",
            extracted_at="t",
        ),
        negated=negated,
    )


def _memoire() -> Memoire:
    memo = Memoire("code")
    memo.observer(
        _noyau("Pluie", "Inondation", "cause", "doc://1", 0.85),
        channel="test",
        fiabilite=0.9,
        horodatage="t1",
    )
    memo.observer(
        _noyau("Pluie", "Inondation", "cause", "doc://2", 0.85),
        channel="test",
        fiabilite=0.9,
        horodatage="t2",
    )
    memo.observer(
        _noyau("Vent", "Sécheresse", "prevent", "doc://3", 0.7),
        channel="test",
        fiabilite=0.5,
        horodatage="t3",
    )
    return memo


def _ctx() -> Context:
    return Context(store=Magasin(Path(tempfile.mkdtemp())), domain="code")


def test_conforme_et_manifeste() -> None:
    assert isinstance(OutilValider({}), Tool)
    assert manifest_from_plugin(OutilValider).name == "validate"


def test_confirmed_source_confiance() -> None:
    recu = OutilValider({"code": _memoire()}).run(
        _ctx(), {"claim": {"source": "Pluie", "relation": "cause", "cible": "Inondation"}}
    )
    assert recu.status is Status.OK
    assert recu.payload["verdict"] == "CONFIRMED"
    assert recu.payload["source"] == "doc://1"
    assert recu.payload["confiance"] == 0.85
    assert recu.payload["confirmations"] == 2


def test_unconfirmed_jamais_faux() -> None:
    recu = OutilValider({"code": _memoire()}).run(
        _ctx(), {"claim": {"source": "Neige", "relation": "cause", "cible": "Retard"}}
    )
    assert recu.status is Status.OK
    assert recu.payload["verdict"] == "UNCONFIRMED"
    assert recu.payload["motif"] == "ni preuve ni réfutation (jamais « faux »)"


def test_contradicted_table() -> None:
    recu = OutilValider({"code": _memoire()}).run(
        _ctx(), {"claim": {"source": "Vent", "relation": "cause", "cible": "Sécheresse"}}
    )
    assert recu.payload["verdict"] == "CONTRADICTED"
    assert recu.payload["source"] == "doc://3"


def test_contradicted_negation() -> None:
    memo = Memoire("code")
    memo.observer(
        _noyau("Soleil", "Nuit", "cause", "doc://9", 0.9, negated=True),
        channel="test",
        fiabilite=0.5,
        horodatage="t",
    )
    recu = OutilValider({"code": memo}).run(
        _ctx(), {"claim": {"source": "Soleil", "relation": "cause", "cible": "Nuit"}}
    )
    assert recu.payload["verdict"] == "CONTRADICTED"


def test_hors_table_unconfirmed() -> None:
    recu = OutilValider({"code": _memoire()}).run(
        _ctx(), {"claim": {"source": "Vent", "relation": "enable", "cible": "Sécheresse"}}
    )
    assert recu.payload["verdict"] == "UNCONFIRMED"  # enable/prevent hors table fermée


def test_quarantaine_exclue() -> None:
    memo = _memoire()
    for env in memo.entites.values():
        env.quarantine = "instruction"
    recu = OutilValider({"code": memo}).run(
        _ctx(), {"claim": {"source": "Pluie", "relation": "cause", "cible": "Inondation"}}
    )
    assert recu.payload["verdict"] == "UNCONFIRMED"


def test_claim_texte_via_extracteur() -> None:
    def _extraire(textes):
        assert textes == ["il pleut donc ça inonde"]
        return ToolResult(
            status=Status.OK,
            payload={
                "cirs": [
                    {
                        "nodes": [{"id": 0, "label": "Pluie"}, {"id": 1, "label": "Inondation"}],
                        "edges": [[0, 1, {"relation": "cause", "confidence": 0.9}]],
                    }
                ]
            },
        )

    recu = OutilValider({"code": _memoire()}, extraire=_extraire).run(
        _ctx(), {"claim": "il pleut donc ça inonde"}
    )
    assert recu.payload["verdict"] == "CONFIRMED"


def test_texte_sans_extracteur_degrade() -> None:
    recu = OutilValider({"code": _memoire()}).run(_ctx(), {"claim": "du texte brut"})
    assert recu.status is Status.DEGRADE


def test_invalides() -> None:
    outil = OutilValider({"code": _memoire()})
    assert outil.run(_ctx(), {"claim": 42}).status is Status.FAILED
    assert (
        outil.run(_ctx(), {"claim": {"source": "", "relation": "cause", "cible": "x"}}).status
        is Status.FAILED
    )
    assert (
        outil.run(
            Context(store=_ctx().store, domain="inconnu"),
            {"claim": {"source": "a", "relation": "cause", "cible": "b"}},
        ).status
        is Status.FAILED
    )
