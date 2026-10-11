# Copyright 2026 Michel Tendeng
# SPDX-License-Identifier: Apache-2.0
"""T3.2 — enveloppement : ref/span/hash par-dessus le marqueur, sans perte."""

from __future__ import annotations

import copy
from typing import Any

import pytest

from evidra.engine_bridge.provenance import envelopper, verifier, vers_noyaux
from evidra.memory.envelope import CodeSpan, TokenSpan


def _cir_moteur() -> dict[str, Any]:
    return {
        "source_text": "Les ventes baissent donc les prix augmentent.",
        "nodes": [
            {"id": 0, "node_type": "condition", "label": "baisse des ventes"},
            {"id": 1, "node_type": "condition", "label": "hausse des prix"},
        ],
        "edges": [
            [
                0,
                1,
                {
                    "relation": "causes",
                    "confidence": 0.87,
                    "explicit": True,
                    "negated": False,
                    "marker_token": 3,
                    "provenance": {
                        "ref": None,
                        "span": "synthetic",
                        "extraction_method": "ml_python",
                        "model_version": "4.0.0",
                        "extracted_at": "2026-10-11T00:00:00Z",
                    },
                },
            ],
            [
                1,
                0,
                {
                    "relation": "prevents",
                    "confidence": 0.4,
                    "explicit": False,
                    "negated": True,
                    "marker_token": None,
                    "provenance": {
                        "ref": None,
                        "span": "synthetic",
                        "extraction_method": "ml_python",
                        "model_version": "4.0.0",
                        "extracted_at": "2026-10-11T00:00:00Z",
                    },
                },
            ],
        ],
    }


TEXTE = "Les ventes baissent donc les prix augmentent."
REF = "doc://rapport-1"


def test_enveloppe_injecte_ref_span_hash() -> None:
    enrichi = envelopper(_cir_moteur(), ref=REF, texte=TEXTE, spans={3: TokenSpan(10, 20)})
    prov = enrichi["edges"][0][2]["provenance"]
    assert prov["ref"] == REF
    assert prov["span"] == {"token_span": {"start": 10, "end": 20}}
    assert len(prov["content_sha256"]) == 64
    assert (
        enrichi["edges"][1][2]["provenance"]["span"] == "synthetic"
    )  # sans table : tracé tel quel
    assert verifier(enrichi, TEXTE) is True


def test_champs_noyau_intacts() -> None:
    brut, enrichi = _cir_moteur(), envelopper(_cir_moteur(), ref=REF, texte=TEXTE)
    assert enrichi["nodes"] == brut["nodes"]
    for avant, apres in zip(brut["edges"], enrichi["edges"], strict=True):
        for champ in ("relation", "confidence", "explicit", "negated", "marker_token"):
            assert apres[2][champ] == avant[2][champ]


def test_entree_non_mutee() -> None:
    brut = _cir_moteur()
    avant = copy.deepcopy(brut)
    envelopper(brut, ref=REF, texte=TEXTE)
    assert brut == avant


def test_ref_existante_preservee() -> None:
    brut = _cir_moteur()
    brut["edges"][0][2]["provenance"]["ref"] = "rust://deja-la"
    enrichi = envelopper(brut, ref=REF, texte=TEXTE)
    assert enrichi["edges"][0][2]["provenance"]["ref"] == "rust://deja-la"


def test_span_code() -> None:
    enrichi = envelopper(_cir_moteur(), ref=REF, texte="x = 1", spans={3: CodeSpan("f.py", 1, 9)})
    assert enrichi["edges"][0][2]["provenance"]["span"] == {
        "code_span": {"file": "f.py", "line_start": 1, "line_end": 9}
    }


def test_entrees_invalides_levent() -> None:
    with pytest.raises(ValueError):
        envelopper("pas-un-cir", ref=REF, texte=TEXTE)  # type: ignore[arg-type]
    with pytest.raises(ValueError):
        envelopper(_cir_moteur(), ref="", texte=TEXTE)
    with pytest.raises(ValueError):
        envelopper(_cir_moteur(), ref=REF, texte=42)  # type: ignore[arg-type]
    with pytest.raises(ValueError):
        envelopper({"nodes": [], "edges": [{"pas": "une-arete"}]}, ref=REF, texte=TEXTE)


def test_verifier_refuse() -> None:
    enrichi = envelopper(_cir_moteur(), ref=REF, texte=TEXTE)
    assert verifier(enrichi, "tout autre texte") is False
    assert verifier("pas-un-cir", TEXTE) is False  # type: ignore[arg-type]
    mutile = copy.deepcopy(enrichi)
    del mutile["edges"][0][2]["provenance"]["ref"]
    assert verifier(mutile, TEXTE) is False


def test_vers_noyaux_sans_perte() -> None:
    enrichi = envelopper(_cir_moteur(), ref=REF, texte=TEXTE, spans={3: TokenSpan(10, 20)})
    (n1, n2) = vers_noyaux(enrichi)
    assert (n1.source, n1.target, n1.relation, n1.confidence) == (
        "baisse des ventes",
        "hausse des prix",
        "causes",
        0.87,
    )
    assert (n1.explicit, n1.negated) == (True, False)
    assert (n2.explicit, n2.negated) == (False, True)
    assert n1.provenance.ref == REF and len(n1.provenance.content_sha256) == 64
    assert n1.provenance.span == TokenSpan(10, 20)


def test_vers_noyaux_refuse_sans_ref() -> None:
    with pytest.raises(ValueError):
        vers_noyaux(_cir_moteur())  # ref None : envelopper d'abord (I4)


def test_vers_noyaux_span_illisible() -> None:
    brut = _cir_moteur()
    brut["edges"][0][2]["provenance"]["span"] = {"bizarre": 1}
    enrichi = envelopper(brut, ref=REF, texte=TEXTE)
    with pytest.raises(ValueError):
        vers_noyaux(enrichi)


def test_i4_bout_en_bout() -> None:
    brut = _cir_moteur()
    assert brut["edges"][0][2]["provenance"]["ref"] is None
    enrichi = envelopper(brut, ref=REF, texte=TEXTE, spans={3: TokenSpan(0, 44)})
    assert verifier(enrichi, TEXTE) is True
    (noyau,) = [n for n in vers_noyaux(enrichi) if n.relation == "causes"]
    assert noyau.provenance.ref == REF
