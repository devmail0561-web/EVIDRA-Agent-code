# Copyright 2026 Michel Tendeng
# SPDX-License-Identifier: Apache-2.0
"""T3.3+T3.4 — graphe matérialisé : incrémental ≡ rebuild, plafonds tenus."""

# ruff: noqa: E402 — la garde importorskip précède volontairement les imports
# moteur : sans moteur importable, aucun import ci-dessous ne peut réussir.
from __future__ import annotations

import pytest

pytest.importorskip("gcn_python", reason="moteur non importable")

from gcn_python.verbalizer.instructions import CausalGraph

from evidra.engine_bridge.graphe import ajouter, empreinte, materialiser
from evidra.memory.envelope import CirCore, Envelope, Provenance
from evidra.memory.index import Index
from evidra.memory.sous_graphe import decouper


def _noyau(src: str, dst: str, relation: str = "cause", confiance: float = 0.8) -> CirCore:
    return CirCore(
        source=src,
        target=dst,
        relation=relation,
        confidence=confiance,
        provenance=Provenance(
            ref="doc://t",
            span="synthetic",
            extraction_method="symbolic_rust",
            model_version="gcn-core-4.0.0",
            extracted_at="2026-10-11T00:00:00Z",
        ),
    )


def test_incremental_egale_rebuild() -> None:
    enveloppes = [
        Envelope(_noyau("gel", "recolte")),
        Envelope(_noyau("recolte", "penurie")),
        Envelope(_noyau("gel", "retard", relation="enable", confiance=0.6)),
    ]
    progressif = CausalGraph()
    for enveloppe in enveloppes:
        ajouter(progressif, enveloppe)
    assert empreinte(progressif) == empreinte(materialiser(enveloppes))


def test_provenance_preservee_et_confiance_intacte() -> None:
    graphe = materialiser([Envelope(_noyau("gel", "recolte", confiance=0.87))])
    [(src, dst, attrs, _)] = [e for e in graphe.edges if e[2].get("relation") == "cause"]
    assert attrs["provenance"]["ref"] == "doc://t"
    assert attrs["confidence"] == 0.87  # poids document = 1.0, sans distorsion
    assert graphe.find_path("gel", "recolte") != []


def test_relation_inconnue_leve() -> None:
    graphe = CausalGraph()
    with pytest.raises(ValueError):
        ajouter(graphe, Envelope(_noyau("a", "b", relation="nimporte-quoi")))


def test_domaine_100k_plafond_tenu() -> None:
    index = Index()
    enveloppes: dict[str, Envelope] = {}

    def _ajouter(ident: str, src: str, dst: str) -> None:
        enveloppes[ident] = Envelope(_noyau(src, dst))
        index.ajouter(ident, src, dst, "cause", 0.8)

    for i in range(3000):
        _ajouter(f"hub-{i:04d}", "noeud-hub", f"feuille-{i:04d}")
    for i in range(97_000):
        _ajouter(f"fond-{i:05d}", f"fond-{i % 4000:04d}", f"fond-{(i * 3 + 1) % 4000:04d}")
    assert len(index) == 100_000
    decoupe = decouper(index, ["noeud-hub"], profondeur=1)
    assert decoupe.tronque > 0
    sous = materialiser(enveloppes[i] for i in decoupe.ids)
    assert len(sous.nodes) <= 500 and len(sous.edges) <= 2000
