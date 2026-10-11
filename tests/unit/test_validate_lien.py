# Copyright 2026 Michel Tendeng
# SPDX-License-Identifier: Apache-2.0
"""T3.5 — coquille validate : trouve = raisonné ET vérifié."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

from evidra.engine_bridge.validate import verifier_lien
from evidra.kernel.contracts import Status


def _graphe() -> Any:
    return SimpleNamespace(edges=[("a", "b", {"relation": "cause", "confidence": 0.8}, "texte")])


def _raison_ok(*args: Any, **kwargs: Any) -> dict[str, Any]:
    return {
        "status": "ok",
        "answer": {"path": ["a", "b"], "confidence": 0.8, "summary": "trouvé", "derived": []},
        "trace": [],
    }


def _verifie_ok(chemin: list, graphe: Any, **kwargs: Any) -> tuple[bool, str]:
    assert kwargs.get("min_conf", 0.0) == 0.5
    return (True, "verified")


def test_lien_trouve_et_verifie() -> None:
    recu = verifier_lien(
        _graphe(),
        "a",
        "b",
        etiquettes={"a": "A", "b": "B"},
        min_conf=0.5,
        raison=_raison_ok,
        verificateur=_verifie_ok,
    )
    assert recu.status is Status.OK
    assert recu.payload["trouve"] is True
    assert recu.payload["verification"] == "verified"
    assert recu.payload["confiance"] == 0.8


def test_chemin_non_verifie_degrade() -> None:
    def _verifie_ko(chemin: list, graphe: Any, **kwargs: Any) -> tuple[bool, str]:
        return (False, "contradiction: a -> b [negated]")

    recu = verifier_lien(
        _graphe(), "a", "b", etiquettes={}, raison=_raison_ok, verificateur=_verifie_ko
    )
    assert recu.status is Status.DEGRADE
    assert recu.payload["trouve"] is False
    assert "non vérifié" in recu.payload["motif"]


def test_sans_preuve_degrade_pas_failed() -> None:
    def _raison_ko(*args: Any, **kwargs: Any) -> dict[str, Any]:
        return {"status": "degrade", "answer": {"summary": "aucun pont"}, "trace": []}

    recu = verifier_lien(
        _graphe(), "x", "y", etiquettes={}, raison=_raison_ko, verificateur=_verifie_ok
    )
    assert recu.status is Status.DEGRADE
    assert recu.payload["trouve"] is False


def test_verification_indecidable_degrade() -> None:
    def _verifie_leve(chemin: list, graphe: Any, **kwargs: Any) -> tuple[bool, str]:
        raise RuntimeError("graphe illisible")

    recu = verifier_lien(
        _graphe(), "a", "b", etiquettes={}, raison=_raison_ok, verificateur=_verifie_leve
    )
    assert recu.status is Status.DEGRADE
    assert recu.payload["trouve"] is False
