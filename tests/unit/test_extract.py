# Copyright 2026 Michel Tendeng
# SPDX-License-Identifier: Apache-2.0
"""T3.1 — coquille extract : stub, erreurs, timeout, copies (logique nulle)."""

from __future__ import annotations

import time
from typing import Any

from evidra.engine_bridge.extract import extraire
from evidra.engine_bridge.moteur import Moteur
from evidra.kernel.contracts import Status


class _MoteurStub:
    def __init__(self, cirs: list[dict[str, Any]] | None = None, latence: float = 0.0) -> None:
        self._cirs = cirs if cirs is not None else [{"nodes": [], "edges": []}]
        self._latence = latence
        self.recus: list[list[str]] = []

    def analyze_batch(self, texts: list[str]) -> list[dict[str, Any]]:
        if self._latence:
            time.sleep(self._latence)
        self.recus.append(list(texts))
        return [self._cirs[0] for _ in texts]  # refs partagées : la coquille doit copier


def test_extraire_ok_passthrough():
    moteur = _MoteurStub([{"nodes": [{"label": "a"}], "edges": []}])
    assert isinstance(moteur, Moteur)
    recu = extraire(["phrase un", "phrase deux"], moteur=moteur, timeout_s=5.0)
    assert recu.status is Status.OK
    assert recu.payload["ignores"] == 0
    assert len(recu.payload["cirs"]) == 2
    assert moteur.recus == [["phrase un", "phrase deux"]]


def test_copies_independantes():
    moteur = _MoteurStub([{"compteurs": [1]}])
    premier = extraire(["x"], moteur=moteur, timeout_s=5.0)
    premier.payload["cirs"][0]["compteurs"].append(999)
    second = extraire(["x"], moteur=moteur, timeout_s=5.0)
    assert second.payload["cirs"][0] == {"compteurs": [1]}


def test_blancs_degade_non_silencieux():
    recu = extraire(["ok", "", "   ", 42], moteur=_MoteurStub(), timeout_s=5.0)  # type: ignore[list-item]
    assert recu.status is Status.DEGRADE
    assert recu.payload["ignores"] == 3
    assert recu.warnings != ()


def test_entrees_invalides_failed_sans_lever():
    assert extraire("pas-une-liste", moteur=_MoteurStub(), timeout_s=5.0).status is Status.FAILED  # type: ignore[arg-type]
    assert extraire(["x"], moteur=None, timeout_s=5.0).status is Status.FAILED
    assert extraire(["x"], moteur=_MoteurStub(), timeout_s=0).status is Status.FAILED
    assert extraire(["x"], moteur=_MoteurStub(), timeout_s=-1.0).status is Status.FAILED


def test_panne_moteur_failed():
    class _MoteurPanne:
        def analyze_batch(self, texts: list[str]) -> list[dict[str, Any]]:
            raise RuntimeError("panne")

    recu = extraire(["x"], moteur=_MoteurPanne(), timeout_s=5.0)  # type: ignore[arg-type]
    assert recu.status is Status.FAILED
    assert "panne" in recu.payload["motif"]


def test_timeout_failed():
    recu = extraire(["x"], moteur=_MoteurStub(latence=0.5), timeout_s=0.01)
    assert recu.status is Status.FAILED
    assert "timeout" in recu.payload["motif"]


def test_moteur_non_liste_failed():
    class _MoteurVide:
        def analyze_batch(self, texts: list[str]) -> list[dict[str, Any]]:
            return "pas-une-liste"  # type: ignore[return-value]

    assert extraire(["x"], moteur=_MoteurVide(), timeout_s=5.0).status is Status.FAILED  # type: ignore[arg-type]
