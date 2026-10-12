# Copyright 2026 Michel Tendeng
# SPDX-License-Identifier: Apache-2.0
"""Politique de sélection (T4.3, §1.3 de l'étude) : situation → outils par niveau.

Table pure priorité → condition → outils (testable sans moteur ni disque).
Vit HORS du noyau : elle nomme des outils concrets (I2). Le scheduler (T4.4)
l'exécute (un outil principal par niveau et par tick) ; les outils eux-mêmes
arrivent en phases 5–6 (`maintenance` = routine mémoire T6.1, pas un outil
branché). Cycle sans condition ⇒ aucun outil.
"""

from __future__ import annotations

from dataclasses import dataclass

from evidra.kernel.scheduler import Priorite

TABLE: tuple[tuple[Priorite, str, tuple[str, ...]], ...] = (
    (Priorite.P1, "alertes_actives", ("alert", "report")),
    (Priorite.P2, "claims", ("validate",)),
    (Priorite.P3, "questions", ("query_causes", "query_effects", "query_chain")),
    (Priorite.P4, "donnees", ("fetch", "extract", "ingest")),
    (Priorite.P5, "stales", ("maintenance",)),
    (Priorite.P6, "fond", ("query_cycles", "query_gaps")),
)


@dataclass(frozen=True, slots=True)
class Situation:
    """État observable en début de cycle (construit par le scheduler, T4.4)."""

    alertes_actives: tuple[str, ...] = ()
    claims: tuple[str, ...] = ()
    questions: tuple[str, ...] = ()
    donnees: tuple[str, ...] = ()
    stales: tuple[str, ...] = ()
    fond: bool = False


def selectionner(situation: Situation) -> dict[Priorite, tuple[str, ...]]:
    """Niveaux actifs dans l'ordre → outils dans l'ordre d'exécution."""
    selection: dict[Priorite, tuple[str, ...]] = {}
    for niveau, champ, outils in TABLE:
        if getattr(situation, champ):
            selection[niveau] = outils
    return selection
