# Copyright 2026 Michel Tendeng
# SPDX-License-Identifier: Apache-2.0
"""Sortie alerte (T5.7) : sévérité + condition + sous-graphe concerné.

Payload structuré pour le système consommateur (SIEM, T7.2) : pas de prose,
graphe partiel joint pour contexte. Sévérités fermées (`info`,
`avertissement`, `critique`) — fail-closed sinon.
"""

from __future__ import annotations

from typing import Any

from evidra.kernel.contracts import ToolResult
from evidra.output.llm import preuves_du_recu

SEVERITES = frozenset({"info", "avertissement", "critique"})


def formater_alerte(resultat: ToolResult, *, severite: str, condition: str) -> dict[str, Any]:
    """`ToolResult` + sévérité/condition → payload d'alerte structuré."""
    if severite not in SEVERITES:
        raise ValueError(f"sévérité inconnue : {severite!r} (info|avertissement|critique)")
    if not isinstance(condition, str) or not condition:
        raise ValueError("condition non vide exigée")
    preuves = preuves_du_recu(resultat)
    noeuds: set[str] = set()
    aretes = []
    for preuve in preuves:
        src, dst = preuve.get("source"), preuve.get("cible")
        noeuds.update([x for x in (src, dst) if isinstance(x, str)])
        prov = preuve.get("provenance")
        ref = prov.get("ref") if isinstance(prov, dict) else None
        aretes.append(
            {
                "de": src,
                "vers": dst,
                "relation": preuve.get("relation"),
                "confiance": preuve.get("confiance"),
                "ref": ref,
            }
        )
    return {
        "severite": severite,
        "condition": condition,
        "preuves": len(preuves),
        "graphe_partiel": {"noeuds": sorted(noeuds), "aretes": aretes},
    }
