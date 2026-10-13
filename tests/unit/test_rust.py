# Copyright 2026 Michel Tendeng
# SPDX-License-Identifier: Apache-2.0
"""Requêtes CLI Rust : anti-injection GCN-QL et validation de requête."""

from __future__ import annotations

import pytest

from evidra.engine_bridge.rust import interroger, interroger_chaine


@pytest.mark.parametrize(
    "mauvais", ["a; CYCLES?", "a->b", "a#comment", 'a"b', "a'b", "a?b", "a\nb"]
)
def test_interroger_chaine_rejette_metacaracteres(mauvais: str) -> None:
    with pytest.raises(ValueError):
        interroger_chaine("gcn", {}, mauvais, "c")
    with pytest.raises(ValueError):
        interroger_chaine("gcn", {}, "c", mauvais)


def test_interroger_rejette_requete_multiligne() -> None:
    with pytest.raises(ValueError):
        interroger("gcn", {}, "CHAIN a -> b?\nCYCLES?")


def test_interroger_chaine_label_vide_rejete() -> None:
    with pytest.raises(ValueError):
        interroger_chaine("gcn", {}, "", "c")
    with pytest.raises(ValueError):
        interroger_chaine("gcn", {}, "   ", "c")
