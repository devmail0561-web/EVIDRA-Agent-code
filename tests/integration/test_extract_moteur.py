# Copyright 2026 Michel Tendeng
# SPDX-License-Identifier: Apache-2.0
"""T3.1 — coquille sur vrai moteur : contrat `Moteur` + CIRs provenancés."""

# ruff: noqa: E402 — la garde importorskip précède volontairement les imports
# moteur : sans moteur importable, aucun import ci-dessous ne peut réussir.
from __future__ import annotations

import pytest

gcn_python = pytest.importorskip("gcn_python", reason="moteur non importable")

from evidra.engine_bridge.extract import extraire
from evidra.engine_bridge.moteur import Moteur
from evidra.kernel.contracts import Status
from tests.essai import moteur_essai


def test_moteur_reel_satisfait_contrat_et_produit() -> None:
    moteur, _reelle = moteur_essai()
    assert isinstance(moteur, Moteur)
    recu = extraire(
        ["Les ventes baissent donc les prix augmentent."], moteur=moteur, timeout_s=30.0
    )
    assert recu.status is Status.OK
    (cir,) = recu.payload["cirs"]
    assert set(cir["edges"][0][2]["provenance"]) >= {
        "ref",
        "span",
        "extraction_method",
        "model_version",
        "extracted_at",
    }
