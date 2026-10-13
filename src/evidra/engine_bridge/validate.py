# Copyright 2026 Michel Tendeng
# SPDX-License-Identifier: Apache-2.0
"""Coquille `validate` (T3.5) : `reason()` + `verify_path` → `ToolResult`.

Trouve = chemin raisonné ET vérifié (`verify_path` public, `min_conf`
transmise). Pas de preuve ⇒ `DEGRADE` (`trouve: False`, jamais `FAILED` —
l'absence de preuve n'est pas une réfutation, §5.3). Les verdicts
`CONFIRMED`/`UNCONFIRMED`/`CONTRADICTED` relèvent de l'outil T5.3.
"""

from __future__ import annotations

import logging
from collections.abc import Callable, Mapping
from typing import Any

from evidra.engine_bridge.reason import _derives_marqués, _normaliser
from evidra.engine_bridge.travailleur import WorkerTimeout, lancer
from evidra.kernel.contracts import Status, ToolResult

Verificateur = Callable[..., Any]

_LOG = logging.getLogger(__name__)


def _raison_moteur_defaut() -> Callable[..., dict[str, Any]]:
    """Import paresseux : `import evidra.engine_bridge.validate` sans moteur OK."""
    from gcn_python.reasoning.engine import reason as raison

    return raison


def _verificateur_moteur_defaut() -> Verificateur:
    """Import paresseux (idem)."""
    from gcn_python.reasoning.engine import verify_path as verifie

    return verifie


def _chemin_ids(reponse: dict[str, Any]) -> list[Any]:
    answer = reponse.get("answer")
    brut = answer.get("path", []) if isinstance(answer, dict) else []
    return list(brut) if isinstance(brut, list) else []


def verifier_lien(
    graphe: Any,
    src_label: str,
    dst_label: str,
    *,
    etiquettes: Mapping[Any, str],
    budget: int = 16,
    min_conf: float = 0.0,
    timeout_s: float | None = None,
    raison: Callable[..., dict[str, Any]] | None = None,
    verificateur: Verificateur | None = None,
) -> ToolResult:
    """Lien causal ? `trouve` + chemin + confiance + preuves citées.

    `timeout_s=None` ⇒ défaut canonique directive (`Budgets.timeout_travailleur_s`, I9).
    """
    from evidra.directive.schema import timeout_travailleur_defaut

    delai = timeout_travailleur_defaut() if timeout_s is None else timeout_s
    if (
        graphe is None
        or not isinstance(src_label, str)
        or not src_label.strip()
        or not isinstance(dst_label, str)
        or not dst_label.strip()
    ):
        return ToolResult(
            status=Status.FAILED, payload={"trouve": False, "motif": "labels invalides"}
        )
    if raison is None or verificateur is None:
        try:
            raison = raison or _raison_moteur_defaut()
            verificateur = verificateur or _verificateur_moteur_defaut()
        except Exception as exc:
            return ToolResult(
                status=Status.FAILED,
                payload={"trouve": False, "motif": f"moteur non importable : {exc}"},
            )
    try:
        reponse = lancer(lambda: raison(src_label, dst_label, graphe, budget=budget), delai)
    except WorkerTimeout:
        return ToolResult(
            status=Status.FAILED,
            payload={"trouve": False, "motif": f"validate en timeout ({delai}s)"},
        )
    except Exception as exc:  # noqa: BLE001 — toute panne moteur devient `failed`
        _LOG.exception("panne moteur validate")
        return ToolResult(
            status=Status.FAILED, payload={"trouve": False, "motif": f"panne moteur : {exc}"}
        )
    if not isinstance(reponse, dict) or reponse.get("status") != "ok":
        motif = ""
        if isinstance(reponse, dict) and isinstance(reponse.get("answer"), dict):
            motif = str(reponse["answer"].get("summary", ""))
        return ToolResult(
            status=Status.DEGRADE,
            payload={
                "trouve": False,
                "motif": motif,
                "chemin": [],
                "confiance": 0.0,
                "preuves": [],
                "derives": _derives_marqués(reponse if isinstance(reponse, dict) else {}),
            },
        )
    normalise = _normaliser(reponse, graphe, etiquettes)
    try:
        verdict = verificateur(_chemin_ids(reponse), graphe, min_conf=min_conf)
    except Exception as exc:  # noqa: BLE001 — vérification indécidable ⇒ pas trouvé
        _LOG.exception("vérification indécidable")
        return ToolResult(
            status=Status.DEGRADE,
            payload={
                "trouve": False,
                **normalise,
                "motif": f"vérification indécidable : {exc}",
                "verification": "",
            },
        )
    ok = bool(verdict[0]) if isinstance(verdict, (list, tuple)) and len(verdict) > 0 else False
    detail = str(verdict[1]) if isinstance(verdict, (list, tuple)) and len(verdict) > 1 else ""
    if ok:
        return ToolResult(
            status=Status.OK,
            payload={"trouve": True, **normalise, "verification": detail or "verified"},
        )
    return ToolResult(
        status=Status.DEGRADE,
        payload={
            "trouve": False,
            **normalise,
            "motif": f"chemin non vérifié : {detail}",
            "verification": detail,
        },
    )
