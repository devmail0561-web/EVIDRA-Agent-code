# Copyright 2026 Michel Tendeng
# SPDX-License-Identifier: Apache-2.0
"""Sortie humain (T5.7) : texte verbalisé, citations en fin, confiance en prose.

Gabarits côté SA (le verbaliseur moteur n'est pas importable, I1).
Anti-injection (I11, §28.2) : le texte source n'apparaît QUE quoté (« ») avec
attribution [n] en fin de paragraphe — jamais fusionné au gabarit, jamais en
position d'instruction. Confiance en prose (+ valeur entre parenthèses).
"""

from __future__ import annotations

from evidra.kernel.contracts import ToolResult
from evidra.output.llm import formater_llm

VERBES = {"cause": "cause", "prevent": "empêche", "enable": "permet", "condition": "conditionne"}


def _en_prose(confiance: object) -> str:
    if not isinstance(confiance, (int, float)):
        return "confiance inconnue"
    if confiance >= 0.85:
        return f"confiance très élevée ({confiance:.2f})"
    if confiance >= 0.65:
        return f"confiance modérée ({confiance:.2f})"
    return f"confiance faible ({confiance:.2f})"


def formater_humain(resultat: ToolResult) -> str:
    """`ToolResult` → paragraphes + citations attribuées en fin."""
    compact = formater_llm(resultat)
    if not compact["faits"]:
        return "Aucune source connue sur ce point."
    lignes = []
    for fait in compact["faits"]:
        verbe = VERBES.get(str(fait["relation"]), str(fait["relation"]))
        lignes.append(
            f"« {fait['de']} » {verbe} « {fait['vers']} » — {_en_prose(fait['confiance'])}."
        )
    lignes.append("")
    lignes.append(
        "Sources : " + "; ".join(f"[{i}] {ref}" for i, ref in enumerate(compact["sources"], 1))
    )
    return "\n".join(lignes)
