# Copyright 2026 Michel Tendeng
# SPDX-License-Identifier: Apache-2.0
"""T0.2 — fumée moteur : le SA importe gcn-python et obtient des CIR.

Construit un pipeline minimal (recette des tests moteur : vocabulaire +
embedding seedé + MLP + RGCN NumPy, SANS checkpoint ni gcn-cli) avec un
parseur stub, et vérifie sur une phrase FR et une EN :
- `analyze` renvoie un CIR `dict` (`source_text`, `nodes`, `edges`) ;
- chaque arête porte la provenance à 5 clés
  (`ref`, `span`, `extraction_method`, `model_version`, `extracted_at`) ;
- `analyze_batch` déduplique et rend des copies indépendantes (M1b).

Si ce test est rouge, tout s'arrête là (gate T0.2).
"""

# ruff: noqa: E402 — la garde importorskip précède volontairement les imports
# moteur : sans moteur importable, aucun import ci-dessous ne peut réussir.
from __future__ import annotations

import pytest

pytest.importorskip("gcn_python", reason="moteur non importable")

from tests.essai import moteur_essai

PROVENANCE_KEYS = {"ref", "span", "extraction_method", "model_version", "extracted_at"}

_PHRASES = {
    "fr": "Les ventes baissent donc les prix augmentent.",
    "en": "Sales fall so prices rise.",
}


def _engine():
    moteur, _reelle = moteur_essai()
    return moteur


def _assert_cir(cir: dict, text: str) -> None:
    assert isinstance(cir, dict)
    assert cir["source_text"] == text
    assert isinstance(cir["nodes"], list) and len(cir["nodes"]) == 2
    assert isinstance(cir["edges"], list) and len(cir["edges"]) >= 1
    for _, _, attrs in cir["edges"]:
        assert set(attrs["provenance"]) >= PROVENANCE_KEYS


def test_analyze_fr_et_en_renvoient_un_cir_provenance():
    engine = _engine()
    for text in _PHRASES.values():
        _assert_cir(engine.analyze(text), text)


def test_analyze_batch_dedup_et_copies_independantes():
    engine = _engine()
    cirs = engine.analyze_batch([_PHRASES["fr"], _PHRASES["fr"], "   ", _PHRASES["en"]])
    assert len(cirs) == 3  # blanc sauté, pas de slot
    assert cirs[0] == cirs[1] and cirs[0] is not cirs[1]
    _assert_cir(cirs[0], _PHRASES["fr"])
    _assert_cir(cirs[2], _PHRASES["en"])
