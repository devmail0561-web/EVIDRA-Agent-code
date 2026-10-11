# Copyright 2026 Michel Tendeng
# SPDX-License-Identifier: Apache-2.0
"""T3.4 — découpe : BFS exact, profondeur, plafonds (sans moteur)."""

from __future__ import annotations

from evidra.memory.index import Index
from evidra.memory.sous_graphe import Decoupe, decouper


def _index_chaine() -> Index:
    index = Index()
    index.ajouter("e1", "A cause", "B effet", "cause", 0.9)
    index.ajouter("e2", "B effet", "C suite", "cause", 0.8)
    index.ajouter("e3", "C suite", "D fin", "cause", 0.7)
    index.ajouter("e4", "B effet", "X branche", "enable", 0.6)
    return index


def test_profondeur_un() -> None:
    decoupe = decouper(_index_chaine(), ["A cause"], profondeur=1)
    assert set(decoupe.ids) == {"e1"}
    assert decoupe.tronque == 0


def test_profondeur_deux() -> None:
    decoupe = decouper(_index_chaine(), ["A cause"], profondeur=2)
    assert set(decoupe.ids) == {"e1", "e2", "e4"}
    assert decoupe.tronque == 0


def test_exact_sans_repli_lexical() -> None:
    index = Index()
    index.ajouter("e1", "authentification", "acces", "cause", 0.9)
    decoupe = decouper(index, ["auth"], profondeur=2)
    assert decoupe.ids == () and decoupe.tronque == 0  # "auth" ≠ "authentification"


def test_plafond_aretes_tronque() -> None:
    decoupe = decouper(_index_chaine(), ["A cause"], profondeur=5, max_aretes=2)
    assert len(decoupe.ids) == 2 and decoupe.tronque > 0


def test_plafond_noeuds_tronque() -> None:
    decoupe = decouper(_index_chaine(), ["A cause"], profondeur=5, max_noeuds=1)
    assert decoupe.ids == () and decoupe.tronque == 1  # coupe arête-complète : e1 saute avec B


def test_amorce_inconnue_vide() -> None:
    decoupe = decouper(_index_chaine(), ["inexistant xyz"], profondeur=2)
    assert isinstance(decoupe, Decoupe)
    assert decoupe.ids == () and decoupe.tronque == 0


def test_bouts() -> None:
    index = _index_chaine()
    assert index.bouts("e1") == ("a cause", "b effet", "cause")
    assert index.bouts("absente") is None
    assert set(index.sortants("B effet")) == {"e2", "e4"}
    assert set(index.entrants("B effet")) == {"e1"}
