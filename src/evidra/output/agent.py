# Copyright 2026 Michel Tendeng
# SPDX-License-Identifier: Apache-2.0
"""Sortie agent (T5.7, machine-machine) : CIR complet + provenance (+ signature P10).

Protocole inter-agents (§8.4) : arêtes avec provenance complète, traçables par
le consommateur (qui applique quarantaine + plafonds, §8.5). `signature` =
`None` jusqu'en phase 9 (T9.2 signe l'enveloppe d'échange, pas ce format).
"""

from __future__ import annotations

from typing import Any

from evidra.kernel.contracts import ToolResult
from evidra.output.llm import preuves_du_recu


def formater_agent(resultat: ToolResult) -> dict[str, Any]:
    """`ToolResult` → CIRs complets + provenance (sans prose, sans perte)."""
    cirs = []
    for preuve in preuves_du_recu(resultat):
        prov = preuve.get("provenance")
        if not isinstance(prov, dict) or not prov.get("ref"):
            continue
        cirs.append(
            {
                "source": preuve.get("source"),
                "target": preuve.get("cible"),
                "relation": preuve.get("relation"),
                "attributes": {
                    "confidence": preuve.get("confiance"),
                    "explicit": preuve.get("explicit", True),
                    "negated": preuve.get("negated", False),
                },
                "provenance": {
                    "ref": prov.get("ref"),
                    "span": prov.get("span"),
                    "extraction_method": prov.get("extraction_method"),
                    "model_version": prov.get("model_version"),
                    "extracted_at": prov.get("extracted_at"),
                },
            }
        )
    return {"format": "cir+provenance", "version": "1", "cirs": cirs, "signature": None}
