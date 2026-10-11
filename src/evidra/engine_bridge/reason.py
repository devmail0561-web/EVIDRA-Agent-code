# Copyright 2026 Michel Tendeng
# SPDX-License-Identifier: Apache-2.0
"""Coquille `reason` (T3.5) : `reason()` → `ToolResult` normalisé.

Paramètres moteur (`budget`) passés en arguments, jamais hardcodés ;
profondeur via la découpe (T3.4, appelant) et top-k interne moteur (TOPK=5,
constaté, non exposé). `query_chain` ne réimplémente jamais Dijkstra (ADR-10).
Les items `derived` du moteur sont transmis marqués `ingestible: False` —
ils ne sont JAMAIS ingérés (acceptation T3.5, règle T3.6) ; les preuves ne
portent que des arêtes vérifiées. Les citations (ref) sont jointes par
l'appelant, propriétaire des enveloppes (T5.2).
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from typing import Any

from gcn_python.reasoning.engine import reason as raison_moteur

from evidra.engine_bridge.travailleur import WorkerTimeout, lancer
from evidra.kernel.contracts import Status, ToolResult

Raisonneur = Callable[..., dict[str, Any]]


def _preuves(graphe: Any, chemin: list[Any], etiquettes: Mapping[Any, str]) -> list[dict[str, Any]]:
    aretes = getattr(graphe, "edges", [])
    preuves = []
    for src, dst in zip(chemin, chemin[1:], strict=False):
        for s, d, attrs, _texte in aretes:
            if s == src and d == dst and isinstance(attrs, dict):
                preuves.append(
                    {
                        "de": etiquettes.get(src, str(src)),
                        "vers": etiquettes.get(dst, str(dst)),
                        "relation": attrs.get("relation"),
                        "confiance": float(attrs.get("confidence", 0.0)),
                    }
                )
                break
    return preuves


def _derives_marqués(reponse: Mapping[str, Any]) -> list[dict[str, Any]]:
    answer = reponse.get("answer")
    derives = answer.get("derived", []) if isinstance(answer, dict) else []
    return [dict(d, ingestible=False) for d in derives if isinstance(d, dict)]


def _normaliser(reponse: Any, graphe: Any, etiquettes: Mapping[Any, str]) -> dict[str, Any]:
    answer = reponse.get("answer", {}) if isinstance(reponse, dict) else {}
    if not isinstance(answer, dict):
        answer = {}
    chemin = answer.get("path", []) if isinstance(answer.get("path"), list) else []
    libelles = [etiquettes.get(n, str(n)) for n in chemin]
    preuves = _preuves(graphe, chemin, etiquettes)
    confiance = min([p["confiance"] for p in preuves] or [float(answer.get("confidence", 0.0))])
    return {
        "chemin": libelles,
        "confiance": confiance,
        "motif": str(answer.get("summary", "")),
        "preuves": preuves,
        "derives": _derives_marqués(reponse if isinstance(reponse, dict) else {}),
    }


def raisonner_chaine(
    graphe: Any,
    de_label: str,
    vers_label: str,
    *,
    etiquettes: Mapping[Any, str],
    budget: int = 16,
    timeout_s: float = 30.0,
    raison: Raisonneur = raison_moteur,
) -> ToolResult:
    """Chaîne causale entre deux labels ; panne ⇒ `failed`, jamais levée."""
    if (
        graphe is None
        or not isinstance(de_label, str)
        or not de_label.strip()
        or not isinstance(vers_label, str)
        or not vers_label.strip()
    ):
        return ToolResult(
            status=Status.FAILED, payload={"trouve": False, "motif": "labels invalides"}
        )
    if not isinstance(budget, int) or isinstance(budget, bool) or budget <= 0:
        return ToolResult(
            status=Status.FAILED, payload={"trouve": False, "motif": "budget invalide"}
        )
    try:
        reponse = lancer(lambda: raison(de_label, vers_label, graphe, budget=budget), timeout_s)
    except WorkerTimeout:
        return ToolResult(
            status=Status.FAILED,
            payload={"trouve": False, "motif": f"reason en timeout ({timeout_s}s)"},
        )
    except Exception as exc:  # noqa: BLE001 — toute panne moteur devient `failed`
        return ToolResult(
            status=Status.FAILED, payload={"trouve": False, "motif": f"panne moteur : {exc}"}
        )
    if not isinstance(reponse, dict):
        return ToolResult(
            status=Status.FAILED, payload={"trouve": False, "motif": "réponse moteur illisible"}
        )
    normalise = _normaliser(reponse, graphe, etiquettes)
    if reponse.get("status") == "ok":
        return ToolResult(status=Status.OK, payload={"trouve": True, **normalise})
    if reponse.get("status") == "degrade":
        return ToolResult(status=Status.DEGRADE, payload={"trouve": False, **normalise})
    return ToolResult(
        status=Status.FAILED, payload={"trouve": False, "motif": "statut moteur inconnu"}
    )
