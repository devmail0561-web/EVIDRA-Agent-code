# Copyright 2026 Michel Tendeng
# SPDX-License-Identifier: Apache-2.0
"""T3.5 — coquilles sur vrai moteur : chaîne trouvée, lien vérifié, degrade."""

# ruff: noqa: E402 — la garde importorskip précède volontairement les imports
# moteur : sans moteur importable, aucun import ci-dessous ne peut réussir.
from __future__ import annotations

import pytest

pytest.importorskip("gcn_python", reason="moteur non importable")

from evidra.engine_bridge.graphe import materialiser
from evidra.engine_bridge.reason import raisonner_chaine
from evidra.engine_bridge.validate import verifier_lien
from evidra.kernel.contracts import Status
from evidra.memory.envelope import CirCore, Envelope, Provenance


def _noyau(src: str, dst: str) -> CirCore:
    return CirCore(
        source=src,
        target=dst,
        relation="cause",
        confidence=0.85,
        provenance=Provenance(
            ref="doc://t",
            span="synthetic",
            extraction_method="symbolic_rust",
            model_version="gcn-core-4.0.0",
            extracted_at="2026-10-11T00:00:00Z",
        ),
    )


def test_chaine_moteur_trouvee() -> None:
    enveloppes = [
        Envelope(_noyau("secheresse", "mauvaise recolte")),
        Envelope(_noyau("mauvaise recolte", "penurie")),
    ]
    graphe = materialiser(enveloppes)
    etiquettes = {
        "secheresse": "Sécheresse",
        "mauvaise recolte": "Mauvaise récolte",
        "penurie": "Pénurie",
    }
    recu = raisonner_chaine(graphe, "secheresse", "penurie", etiquettes=etiquettes)
    assert recu.status is Status.OK
    assert recu.payload["trouve"] is True
    assert len(recu.payload["preuves"]) >= 1
    assert recu.payload["confiance"] > 0.0


def test_lien_moteur_verifie() -> None:
    graphe = materialiser([Envelope(_noyau("secheresse", "mauvaise recolte"))])
    recu = verifier_lien(graphe, "secheresse", "mauvaise recolte", etiquettes={})
    assert recu.status is Status.OK
    assert recu.payload["trouve"] is True


def test_inconnu_degrade() -> None:
    graphe = materialiser([Envelope(_noyau("secheresse", "mauvaise recolte"))])
    assert (
        raisonner_chaine(graphe, "zzzintrouvable", "yyyabsent", etiquettes={}).status
        is Status.DEGRADE
    )
    assert (
        verifier_lien(graphe, "zzzintrouvable", "yyyabsent", etiquettes={}).status is Status.DEGRADE
    )
