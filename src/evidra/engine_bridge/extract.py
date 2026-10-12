# Copyright 2026 Michel Tendeng
# SPDX-License-Identifier: Apache-2.0
"""Coquille `extract` (T3.1, `engine_bridge/extract.py`) : `docs → [CIR]`.

Via `analyze_batch` (dédup M1b prouvée côté moteur), exécuté en worker avec
timeout (patch P3). **Logique nulle** : conversion d'erreurs en
`ToolResult(failed)`, copies profondes en entrée ET sortie (le cache moteur
retourne des copies — on ne partage jamais de référence mutable).
Blancs/non-texte = `ignores` comptés (`degrade`), jamais silencieux.

Aucun import `gcn` ici ni ailleurs hors de ce paquet (garde I1, T0.4) : le
moteur est injecté (T4.5), jamais importé.
"""

from __future__ import annotations

import copy
import logging

from evidra.engine_bridge.moteur import Moteur
from evidra.engine_bridge.travailleur import WorkerTimeout, lancer
from evidra.kernel.contracts import Status, ToolResult

_LOG = logging.getLogger(__name__)


def extraire(documents: list[str], *, moteur: Moteur | None, timeout_s: float = 30.0) -> ToolResult:
    """Extrait des CIRs ; entrée invalide ou panne moteur ⇒ `failed` (jamais levée)."""
    if not isinstance(documents, list):
        return _echec("documents : liste exigée")
    if not isinstance(moteur, Moteur):
        return _echec("moteur indisponible ou hors contrat")
    if not isinstance(timeout_s, (int, float)) or timeout_s <= 0:
        return _echec(f"timeout invalide : {timeout_s!r}")
    valides = [d for d in documents if isinstance(d, str) and d.strip()]
    ignores = len(documents) - len(valides)
    if not valides:
        return ToolResult(status=Status.OK, payload={"cirs": [], "ignores": ignores})
    try:
        cirs = lancer(lambda: moteur.analyze_batch(copy.deepcopy(valides)), float(timeout_s))
    except WorkerTimeout:
        return _echec(f"extraction en timeout ({timeout_s}s)")
    except Exception as exc:  # noqa: BLE001 — toute panne moteur devient `failed`
        _LOG.exception("panne moteur extract")
        return _echec(f"panne moteur : {exc}")
    if not isinstance(cirs, list):
        return _echec("moteur : analyze_batch n'a pas renvoyé une liste")
    copies = copy.deepcopy(cirs)
    if ignores:
        return ToolResult(
            status=Status.DEGRADE,
            payload={"cirs": copies, "ignores": ignores},
            warnings=(f"{ignores} document(s) ignoré(s) (vide ou non-texte)",),
        )
    return ToolResult(status=Status.OK, payload={"cirs": copies, "ignores": 0})


def _echec(motif: str) -> ToolResult:
    return ToolResult(status=Status.FAILED, payload={"cirs": [], "ignores": 0, "motif": motif})
