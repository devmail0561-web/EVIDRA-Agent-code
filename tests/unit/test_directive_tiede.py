# Copyright 2026 Michel Tendeng
# SPDX-License-Identifier: Apache-2.0
"""T4.2 — tiède : inchangé/invalide/supprimé/modifié, registre, arrêt polling."""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from evidra.directive.loader import charger
from evidra.directive.reload import Surveillant, diff_sources
from evidra.directive.schema import valider
from evidra.kernel.registry import PluginState, Registry
from evidra.logging import DirectiveError


def _directive(sources: list[str]) -> dict[str, Any]:
    return {
        "agent_id": "test",
        "domain": "code",
        "sources": [{"adapter": nom, "config": {}} for nom in sources],
    }


def _classe(nom: str = "faux"):
    attrs: dict[str, Any] = {
        "name": nom,
        "version": "0.1.0",
        "harness_required": "1.0",
        "permissions": [],
        "channels": ["test"],
        "cost_hint": {"ms": 1.0, "calls": 1},
        "input_schema": {},
        "output_schema": {},
        "requires_network": False,
    }
    return type("FauxPlugin", (), attrs)


def _registre_adaptateur() -> Registry:
    registre = Registry()
    registre.discover(
        {"evidra_adapters": [SimpleNamespace(name="local_files", load=lambda: _classe())]}
    )
    registre.approve("evidra_adapters:local_files", _classe())
    registre.enable("evidra_adapters:local_files")
    registre.start("evidra_adapters:local_files")
    return registre


def _ecrire(chemin: Path, sources: list[str]) -> None:
    chemin.write_text(json.dumps(_directive(sources)), encoding="utf-8")


def test_charger_valide_invalide_manquante(tmp_path: Path) -> None:
    chemin = tmp_path / "directive.json"
    _ecrire(chemin, ["local_files"])
    assert charger(chemin).domain == "code"
    chemin.write_text("{ invalide", encoding="utf-8")
    with pytest.raises(DirectiveError):
        charger(chemin)
    with pytest.raises(DirectiveError):
        charger(tmp_path / "absente.json")


def test_inchange_pas_de_rechargement(tmp_path: Path) -> None:
    chemin = tmp_path / "directive.json"
    _ecrire(chemin, ["local_files"])
    gardien = Surveillant(chemin, charger(chemin))
    meme, changee = gardien.rafraichir()
    assert changee is False and meme.domain == "code"
    assert gardien.alertes == []


def test_modifiee_bascule_et_hash(tmp_path: Path) -> None:
    chemin = tmp_path / "directive.json"
    _ecrire(chemin, ["local_files"])
    gardien = Surveillant(chemin, charger(chemin))
    avant = gardien.empreinte_courante()
    _ecrire(chemin, ["local_files", "http_feed"])
    nouvelle, changee = gardien.rafraichir()
    assert changee is True
    assert [s.adapter for s in nouvelle.sources] == ["local_files", "http_feed"]
    assert gardien.empreinte_courante() != avant


def test_invalide_ancienne_conservee_et_alerte(tmp_path: Path) -> None:
    chemin = tmp_path / "directive.json"
    _ecrire(chemin, ["local_files"])
    gardien = Surveillant(chemin, charger(chemin))
    chemin.write_text(json.dumps({"agent_id": "x"}), encoding="utf-8")
    meme, changee = gardien.rafraichir()
    assert changee is False and [s.adapter for s in meme.sources] == ["local_files"]
    assert len(gardien.alertes) == 1


def test_supprimee_ancienne_conservee_et_alerte(tmp_path: Path) -> None:
    chemin = tmp_path / "directive.json"
    _ecrire(chemin, ["local_files"])
    gardien = Surveillant(chemin, charger(chemin))
    chemin.unlink()
    meme, changee = gardien.rafraichir()
    assert changee is False and meme.domain == "code"
    assert len(gardien.alertes) == 1


def test_diff_sources() -> None:
    diff = diff_sources(valider(_directive(["a", "b"])), valider(_directive(["b", "c"])))
    assert diff.ajoutees == ("c",) and diff.retirees == ("a",)


def test_retrait_desactive_arrete_polling(tmp_path: Path) -> None:
    chemin = tmp_path / "directive.json"
    _ecrire(chemin, ["local_files"])
    registre = _registre_adaptateur()
    gardien = Surveillant(chemin, charger(chemin), registre)
    polls = []

    def tick():
        fiche = registre._fiches["evidra_adapters:local_files"]
        if fiche.state is PluginState.RUNNING:
            polls.append(1)

    tick()
    _ecrire(chemin, [])
    nouvelle, changee = gardien.rafraichir()
    assert changee is True and nouvelle.sources == []
    assert registre._fiches["evidra_adapters:local_files"].state is PluginState.DISABLED
    tick()
    assert polls == [1]  # aucun polling après le retrait


def test_inconnu_alerte_sans_crash(tmp_path: Path) -> None:
    chemin = tmp_path / "directive.json"
    _ecrire(chemin, ["local_files"])
    gardien = Surveillant(chemin, charger(chemin), Registry())
    _ecrire(chemin, [])
    _, changee = gardien.rafraichir()
    assert changee is True
    assert len(gardien.alertes) == 1
