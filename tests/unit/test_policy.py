# Copyright 2026 Michel Tendeng
# SPDX-License-Identifier: Apache-2.0
"""T4.3 — politique : table fidèle, sélection pure, cycle vide."""

from __future__ import annotations

from evidra.kernel.scheduler import Priorite
from evidra.policy import TABLE, Situation, selectionner


def test_cycle_vide_aucun_outil() -> None:
    assert selectionner(Situation()) == {}


def test_table_fidele_et_ordonnee() -> None:
    assert [n for n, _, _ in TABLE] == [
        Priorite.P1,
        Priorite.P2,
        Priorite.P3,
        Priorite.P4,
        Priorite.P5,
        Priorite.P6,
    ]
    assert TABLE[0][2] == ("alert", "report")
    assert TABLE[1][2] == ("validate",)
    assert TABLE[3][2] == ("fetch", "extract", "ingest")
    assert TABLE[5][2] == ("query_cycles", "query_gaps")
    for _, champ, outils in TABLE:
        assert champ in Situation.__dataclass_fields__
        assert outils and all(isinstance(o, str) and o for o in outils)


def test_niveaux_isoles() -> None:
    assert selectionner(Situation(alertes_actives=("a",))) == {Priorite.P1: ("alert", "report")}
    assert selectionner(Situation(claims=("c",))) == {Priorite.P2: ("validate",)}
    assert selectionner(Situation(questions=("q",))) == {
        Priorite.P3: ("query_causes", "query_effects", "query_chain")
    }
    assert selectionner(Situation(donnees=("d",))) == {Priorite.P4: ("fetch", "extract", "ingest")}
    assert selectionner(Situation(stales=("s",))) == {Priorite.P5: ("maintenance",)}
    assert selectionner(Situation(fond=True)) == {Priorite.P6: ("query_cycles", "query_gaps")}


def test_tout_plein_ordre_strict() -> None:
    pleine = Situation(
        alertes_actives=("a",),
        claims=("c",),
        questions=("q",),
        donnees=("d",),
        stales=("s",),
        fond=True,
    )
    assert list(selectionner(pleine)) == [
        Priorite.P1,
        Priorite.P2,
        Priorite.P3,
        Priorite.P4,
        Priorite.P5,
        Priorite.P6,
    ]
