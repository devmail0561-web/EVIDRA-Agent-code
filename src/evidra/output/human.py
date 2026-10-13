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


def _en_prose(confiance: object, haut: float, moyen: float) -> str:
    if not isinstance(confiance, (int, float)):
        return "confiance inconnue"
    if confiance >= haut:
        return f"confiance très élevée ({confiance:.2f})"
    if confiance >= moyen:
        return f"confiance modérée ({confiance:.2f})"
    return f"confiance faible ({confiance:.2f})"


def formater_humain(resultat: ToolResult, seuils: tuple[float, float] | None = None) -> str:
    """`ToolResult` → paragraphes + citations attribuées en fin.

    `seuils=None` ⇒ tiers canoniques de la directive (`Qualite.seuils_tiers`,
    I9) — jamais de seuils gelés ici (l'ancienne paire 0.85/0.65 dupliquait
    le schéma).
    """
    from evidra.directive.schema import seuils_tiers_defaut

    haut, moyen = seuils if seuils is not None else seuils_tiers_defaut()
    compact = formater_llm(resultat)
    if not compact["faits"]:
        return "Aucune source connue sur ce point."
    lignes = []
    for fait in compact["faits"]:
        verbe = VERBES.get(str(fait["relation"]), str(fait["relation"]))
        prose = _en_prose(fait["confiance"], haut, moyen)
        lignes.append(f"« {fait['de']} » {verbe} « {fait['vers']} » — {prose}.")
    lignes.append("")
    lignes.append(
        "Sources : " + "; ".join(f"[{i}] {ref}" for i, ref in enumerate(compact["sources"], 1))
    )
    return "\n".join(lignes)
