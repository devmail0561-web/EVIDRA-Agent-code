# Copyright 2026 Michel Tendeng
# SPDX-License-Identifier: Apache-2.0
"""T3.9 — tranche sur sous-ensemble (12 phrases) : harness complet, intégrité ≈ 1.0."""

# ruff: noqa: E402 — la garde importorskip précède volontairement les imports
from __future__ import annotations

from pathlib import Path

import pytest

gcn_python = pytest.importorskip("gcn_python", reason="moteur non importable")

from evidra.engine_bridge.binaire import trouver_binaire
from evidra.engine_bridge.extract import extraire
from evidra.engine_bridge.graphe import materialiser
from evidra.engine_bridge.provenance import vers_noyaux
from evidra.kernel.contracts import Context, Verb
from evidra.kernel.gate import Policy, Rule
from evidra.memory.memoire import Memoire
from evidra.memory.store import Magasin
from evidra.tools.ingest import OutilIngest, Seuils
from tests.bench.tranche import (
    charger_gold,
    envelopper_phrase,
    mesurer_nombres,
    paires_croisees,
    triplets_extraits,
    valider_paires,
)
from tests.essai import moteur_essai

GOLD_DEFAUT = Path(__file__).resolve().parent.parent.parent / "benchmarks" / "gold-219.json"


def _harness():
    memo = Memoire("gold")
    policy = Policy(allowed=frozenset({Rule("ingest", Verb.INGEST, "*")}))
    seuils = Seuils(min_confiance=0.0, methodes=frozenset({"ml_python", "symbolic_rust"}))
    outil = OutilIngest({"gold": memo}, policy, seuils, lambda: "2026-10-12T00:00:00Z")
    return memo, outil


def test_tranche_subset_integrite() -> None:
    couvertes, exclues = charger_gold(GOLD_DEFAUT)
    assert len(couvertes) + len(exclues) == 219
    assert len(exclues) == 24  # es : pas de lattice, documenté
    memo, outil = _harness()
    binaire = trouver_binaire()
    moteurs = {}
    subset = [p for p in couvertes if p["lang"] == "fr"][:6] + [
        p for p in couvertes if p["lang"] == "en"
    ][:6]
    import tempfile

    with tempfile.TemporaryDirectory() as tmp, Magasin(Path(tmp)) as magasin:
        ctx = Context(store=magasin, domain="gold")
        cirs = []
        for phrase in subset:
            moteurs.setdefault(
                phrase["lang"],
                moteur_essai(
                    binaire, sous_commande={"fr": "analyze", "en": "analyze-en"}[phrase["lang"]]
                )[0],
            )
            recu = extraire([phrase["texte"]], moteur=moteurs[phrase["lang"]], timeout_s=60.0)
            assert recu.status.value == "ok"
            (cir,) = recu.payload["cirs"]
            if not cir.get("edges"):
                continue  # pas de lien extrait : hors intégrité, documenté
            cirs.append(cir)
            enrichi = envelopper_phrase(cir, phrase["sid"], phrase["texte"])
            noyaux = vers_noyaux(enrichi)
            assert noyaux != []
            outil.run(ctx, {"noyaux": noyaux, "channel": "gold"})
        assert cirs != []  # au moins une phrase productive, sinon test vide
        graphe = materialiser(memo.entites.values())
        consistance = triplets_extraits(cirs)
        couverts = sum(1 for t in set(consistance) if ("gold", t[0], t[1], t[2]) in memo.entites)
        assert couverts == len(set(consistance))  # intégrité : tout triplet extrait ingéré
        gold_triplets = [t for p in subset for t in p["triplets"]]
        cross = paires_croisees(gold_triplets, len(gold_triplets))
        trouves_gold, lat1 = valider_paires(graphe, gold_triplets)
        trouves_cross, lat2 = valider_paires(graphe, cross)
        nombres = mesurer_nombres(trouves_gold, trouves_cross, lat1 + lat2, 1.0, len(subset))
        assert set(nombres) >= {
            "precision_confirmed",
            "rappel_confirmed",
            "taux_unconfirmed",
            "latence_mediane_ms",
            "latence_p99_ms",
            "docs_sec",
        }
