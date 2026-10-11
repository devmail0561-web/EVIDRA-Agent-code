# Copyright 2026 Michel Tendeng
# SPDX-License-Identifier: Apache-2.0
"""T3.5 — coquille reason : normalisation, derived marqués, contrat anti-ingest."""

from __future__ import annotations

import time
from types import SimpleNamespace
from typing import Any

from evidra.engine_bridge.reason import raisonner_chaine
from evidra.kernel.contracts import Status


def _graphe() -> Any:
    return SimpleNamespace(edges=[("a", "b", {"relation": "cause", "confidence": 0.8}, "texte")])


def _etiquettes() -> dict[str, str]:
    return {"a": "Pluie", "b": "Inondation"}


def _raison_ok(*args: Any, **kwargs: Any) -> dict[str, Any]:
    return {
        "status": "ok",
        "answer": {"path": ["a", "b"], "confidence": 0.8, "summary": "trouvé", "derived": []},
        "trace": [],
    }


def test_chaine_ok_preuves_confiance() -> None:
    recu = raisonner_chaine(
        _graphe(), "pluie", "inondation", etiquettes=_etiquettes(), raison=_raison_ok
    )
    assert recu.status is Status.OK
    assert recu.payload["trouve"] is True
    assert recu.payload["chemin"] == ["Pluie", "Inondation"]
    assert recu.payload["confiance"] == 0.8
    (preuve,) = recu.payload["preuves"]
    assert (preuve["de"], preuve["vers"], preuve["relation"]) == ("Pluie", "Inondation", "cause")


def test_chaine_degrade_sans_preuve() -> None:
    def _raison(*args: Any, **kwargs: Any) -> dict[str, Any]:
        return {"status": "degrade", "answer": {"summary": "aucun pont"}, "trace": []}

    recu = raisonner_chaine(_graphe(), "x", "y", etiquettes={}, raison=_raison)
    assert recu.status is Status.DEGRADE
    assert recu.payload["trouve"] is False
    assert recu.payload["motif"] == "aucun pont"


def test_derives_marques_non_ingestibles() -> None:
    def _raison_pont(*args: Any, **kwargs: Any) -> dict[str, Any]:
        return {
            "status": "ok",
            "answer": {
                "path": ["a", "b"],
                "confidence": 0.6,
                "summary": "pont",
                "derived": [
                    {
                        "path": ["a", "x", "b"],
                        "derivation": "derived",
                        "confidence": 0.6,
                        "premises": ["a->x", "x->b"],
                    }
                ],
            },
            "trace": [],
        }

    recu = raisonner_chaine(_graphe(), "a", "b", etiquettes={}, raison=_raison_pont)
    (derive,) = recu.payload["derives"]
    assert derive["derivation"] == "derived"
    assert derive["ingestible"] is False


def test_contrat_aucun_derive_ingere() -> None:
    """Règle T3.6 miroir : un item non ingestible ou `derived` est refusé."""

    def accepter(item: dict[str, Any]) -> bool:
        return bool(item.get("ingestible", True)) and item.get("derivation") != "derived"

    def _raison_pont(*args: Any, **kwargs: Any) -> dict[str, Any]:
        return {
            "status": "ok",
            "answer": {
                "path": ["a", "b"],
                "confidence": 0.6,
                "summary": "pont",
                "derived": [{"path": ["a", "x", "b"], "derivation": "derived", "confidence": 0.6}],
            },
            "trace": [],
        }

    recu = raisonner_chaine(_graphe(), "a", "b", etiquettes={}, raison=_raison_pont)
    ingeres = [d for d in recu.payload["derives"] if accepter(d)]
    assert ingeres == []
    assert all(accepter(p) for p in recu.payload["preuves"])


def test_entrees_invalides_et_pannes() -> None:
    assert raisonner_chaine(None, "a", "b", etiquettes={}).status is Status.FAILED
    assert raisonner_chaine(_graphe(), "", "b", etiquettes={}).status is Status.FAILED
    assert raisonner_chaine(_graphe(), "a", "b", etiquettes={}, budget=0).status is Status.FAILED

    def _panne(*args: Any, **kwargs: Any) -> dict[str, Any]:
        raise RuntimeError("moteur en panne")

    assert (
        raisonner_chaine(_graphe(), "a", "b", etiquettes={}, raison=_panne).status is Status.FAILED
    )
    assert (
        raisonner_chaine(
            _graphe(), "a", "b", etiquettes={}, raison=lambda *a, **k: "pas-un-dict"
        ).status
        is Status.FAILED
    )  # type: ignore[arg-type]

    def _lente(*args: Any, **kwargs: Any) -> dict[str, Any]:
        time.sleep(0.5)
        return {}

    recu = raisonner_chaine(_graphe(), "a", "b", etiquettes={}, raison=_lente, timeout_s=0.01)
    assert recu.status is Status.FAILED
