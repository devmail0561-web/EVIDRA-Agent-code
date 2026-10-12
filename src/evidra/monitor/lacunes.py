# Copyright 2026 Michel Tendeng
# SPDX-License-Identifier: Apache-2.0
"""Lacunes orientées objectif (T7.3) : gaps → questions → tâches P4, pur.

Pour chaque chaîne surveillée : formule « quelles sources acquérir pour
compléter X→Y ? », priorise les lacunes du domaine surveillé sur les
nœuds orphelins hors périmètre, planifie une tâche P4 budgétée
(type `fetch`, pipeline F1 — consommateur futur, jamais exécutée ici).
Pur : les gaps sont fournis par l'appelant (outil `query_gaps`, CLI).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True, slots=True)
class QuestionLacune:
    """Question d'acquisition : quoi chercher, pour quelle chaîne, priorité."""

    question: str
    chaine: tuple[str, ...]
    lacunes: tuple[str, ...]
    prioritaire: bool


def formuler(chaine: list[str], lacunes: list[str]) -> QuestionLacune:
    """Formulation canonique + priorité (lacune non vide ⇒ prioritaire)."""
    texte = " ; ".join(str(x) for x in chaine)
    manquants = " ; ".join(str(x) for x in lacunes)
    return QuestionLacune(
        question=f"quelles sources acquérir pour compléter {texte} ? lacunes : {manquants}",
        chaine=tuple(str(x) for x in chaine),
        lacunes=tuple(str(x) for x in lacunes),
        prioritaire=bool(lacunes),
    )


def planifier(
    chaines: list[list[str]],
    gaps_par_chaine: dict[str, list[str]],
) -> list[QuestionLacune]:
    """Chaînes surveillées (directive) → questions, prioritaires d'abord (stable).

    Les chaînes viennent de `watch_gaps_in_chains` (périmètre surveillé) :
    leurs lacunes priment par construction sur tout hors-périmètre.
    """
    questions = []
    for chaine in chaines:
        if not chaine:
            continue
        cle = ">".join(str(x) for x in chaine)
        questions.append(formuler(list(chaine), list(gaps_par_chaine.get(cle, []))))
    questions.sort(key=lambda q: (not q.prioritaire, q.chaine))
    return questions


def fiche_tache(
    question: QuestionLacune, *, budget: float, deadline: str, rang: int
) -> dict[str, Any]:
    """Charge utile d'une tâche P4 `fetch` (budgétée, traçable)."""
    return {
        "type": "fetch",
        "budget": budget,
        "deadline": deadline,
        "question": question.question,
        "chaine": list(question.chaine),
        "lacunes": list(question.lacunes),
        "prioritaire": question.prioritaire,
        "rang": rang,
    }
