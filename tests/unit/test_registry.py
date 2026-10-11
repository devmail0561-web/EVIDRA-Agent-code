# Copyright 2026 Michel Tendeng
# SPDX-License-Identifier: Apache-2.0
"""T1.3 — registre : découverte factice, transitions, quarantaine auto."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest

from evidra.kernel.registry import PluginState, Registry, RegistryError


def _classe_bonne(**surcharges: Any) -> type:
    attrs: dict[str, Any] = {
        "name": "bon",
        "version": "0.1.0",
        "harness_required": "1.0",
        "permissions": [{"verb": "read", "scope": "*"}],
        "channels": ["test"],
        "cost_hint": {"ms": 1.0, "calls": 1},
        "input_schema": {},
        "output_schema": {},
        "requires_network": False,
    }
    attrs.update(surcharges)
    return type("BonPlugin", (), attrs)


def _points(**plugins: Any) -> dict[str, list[Any]]:
    return {
        "evidra_tools": [
            SimpleNamespace(name=nom, load=lambda cls=cls: cls) for nom, cls in plugins.items()
        ]
    }


def test_decouverte_approve_enable_start():
    registre = Registry()
    registre.discover(_points(bon=_classe_bonne()))
    cle = "evidra_tools:bon"
    assert registre.approve(cle, _classe_bonne()).state is PluginState.VALIDATED
    assert registre.enable(cle).state is PluginState.ENABLED
    assert registre.start(cle).state is PluginState.RUNNING
    rapport = registre.rapport()
    assert rapport.entrees == (("bon", "running", ""),)


def test_harness_trop_recent_desactive_motive():
    registre = Registry()
    registre.discover(_points(futur=_classe_bonne(harness_required="9.9")))
    fiche = registre.approve("evidra_tools:futur", _classe_bonne(harness_required="9.9"))
    assert fiche.state is PluginState.DISABLED
    assert "supporté" in fiche.motif


def test_manifeste_invalide_desactive_motive():
    registre = Registry()
    registre.discover(_points(casse=type("Casse", (), {"name": "casse"})))
    fiche = registre.approve("evidra_tools:casse", type("Casse", (), {"name": "casse"}))
    assert fiche.state is PluginState.DISABLED
    assert "manifeste refusé" in fiche.motif


def test_trois_echecs_quarantaine_auto():
    registre = Registry()
    registre.discover(_points(bon=_classe_bonne()))
    cle = "evidra_tools:bon"
    registre.approve(cle, _classe_bonne())
    registre.enable(cle)
    registre.start(cle)
    registre.note_failure(cle)
    registre.note_failure(cle)
    assert registre._fiche(cle).state is PluginState.RUNNING
    registre.note_failure(cle)
    fiche = registre._fiche(cle)
    assert fiche.state is PluginState.QUARANTINED
    assert "3 échecs" in fiche.motif


def test_succes_remet_compteur_a_zero():
    registre = Registry()
    registre.discover(_points(bon=_classe_bonne()))
    cle = "evidra_tools:bon"
    registre.approve(cle, _classe_bonne())
    registre.enable(cle)
    registre.start(cle)
    registre.note_failure(cle)
    registre.note_success(cle)
    registre.note_failure(cle)
    registre.note_failure(cle)
    assert registre._fiche(cle).state is PluginState.RUNNING


def test_transition_illegale_leve():
    registre = Registry()
    registre.discover(_points(bon=_classe_bonne()))
    with pytest.raises(RegistryError):
        registre.start("evidra_tools:bon")  # discovered → running interdit
    with pytest.raises(RegistryError):
        registre.enable("evidra_tools:inconnu")


def test_desactive_puis_reactive_tiede():
    registre = Registry()
    registre.discover(_points(bon=_classe_bonne()))
    cle = "evidra_tools:bon"
    registre.approve(cle, _classe_bonne())
    registre.enable(cle)
    assert registre.disable(cle, "directive").state is PluginState.DISABLED
    assert registre.enable(cle).state is PluginState.ENABLED
