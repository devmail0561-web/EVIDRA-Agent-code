# Copyright 2026 Michel Tendeng
# SPDX-License-Identifier: Apache-2.0
"""Utilitaires partagés du SA (hors noyau) : bornage, garde d'outils.

`borner()` vivait dans `evidra.boucle` (import `tools/report` → `boucle`
: inversion de couche) ; il vit ici, `boucle.borner` reste un alias
re-exporté (compat). `garde()` factorise le `try/except` des outils
(`run` ne lève jamais → `FAILED` + stack loggée).
"""

from __future__ import annotations

import importlib.metadata
import logging
from collections.abc import Callable

from evidra.kernel.contracts import Status, ToolResult

_LOG = logging.getLogger(__name__)


def version_moteur() -> str:
    """Version du moteur installé (`unknown` si introuvable — jamais levée).

    Lecture de métadonnées de distribution uniquement (aucun import `gcn`) :
    utilisable depuis `boot` sans violer I1.
    """
    try:
        return importlib.metadata.version("gcn-python")
    except Exception:  # noqa: BLE001 — absence = info, pas erreur
        return "unknown"


def borner(items: list, maximum: int, *, score: Callable[[object], float]) -> tuple[list, int]:
    """Dégrade par score : retient les `maximum` meilleurs, `tronqué` compté."""
    if maximum < 0:
        raise ValueError(f"maximum négatif : {maximum}")
    ranges = sorted(items, key=score, reverse=True)
    return ranges[:maximum], max(0, len(ranges) - maximum)


def garde(
    nom_outil: str, func: Callable[[], ToolResult], *, journal: logging.Logger | None = None
) -> ToolResult:
    """Exécute `func` ; panne ⇒ reçu `FAILED` tracé (stack loggée).

    `journal` = logger de l'appelant (filtrage `evidra.tools.<nom>`) ;
    défaut : `evidra.util`.
    """
    log = journal if journal is not None else _LOG
    try:
        return func()
    except Exception as exc:  # noqa: BLE001 — l'outil ne lève jamais
        log.exception("panne outil %s", nom_outil)
        return ToolResult(status=Status.FAILED, payload={"motif": f"panne {nom_outil} : {exc}"})
