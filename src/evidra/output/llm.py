# Copyright 2026 Michel Tendeng
# SPDX-License-Identifier: Apache-2.0
"""Sortie LLM (T5.7) : JSON compact — faits, sources, confiances, sans prose.

Le LLM lit, il ne reformule pas : que des données (listes de faits avec
confiance, refs triées uniques, minimum, avertissements, coût). Aucune
affirmation sans ref (I4) — une preuve sans ref est écartée, comptée.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from evidra.kernel.contracts import ToolResult


def preuves_du_recu(resultat: ToolResult) -> list[dict[str, Any]]:
    charge = resultat.payload if isinstance(resultat.payload, Mapping) else {}
    trouves = []
    for cle in ("reponses", "preuves"):
        contenu = charge.get(cle)
        if isinstance(contenu, list):
            trouves.extend(p for p in contenu if isinstance(p, dict))
    chemin = charge.get("chemin")
    if isinstance(chemin, dict) and isinstance(chemin.get("preuves"), list):
        trouves.extend(p for p in chemin["preuves"] if isinstance(p, dict))
    return trouves


def formater_llm(resultat: ToolResult) -> dict[str, Any]:
    """`ToolResult` → faits compacts + sources + confiance min (zéro prose)."""
    faits, sources, sans_ref = [], [], 0
    for preuve in preuves_du_recu(resultat):
        prov = preuve.get("provenance")
        ref = prov.get("ref") if isinstance(prov, dict) else None
        if not ref:
            sans_ref += 1
            continue
        faits.append(
            {
                "de": preuve.get("source"),
                "vers": preuve.get("cible"),
                "relation": preuve.get("relation"),
                "confiance": preuve.get("confiance"),
            }
        )
        if ref not in sources:
            sources.append(ref)
    confiances = [f["confiance"] for f in faits if isinstance(f["confiance"], (int, float))]
    return {
        "faits": faits,
        "sources": sorted(sources),
        "confiance_min": min(confiances) if confiances else None,
        "sans_ref_ecartees": sans_ref,
        "avertissements": list(resultat.warnings),
        "cout_ms": resultat.cost.ms,
    }
