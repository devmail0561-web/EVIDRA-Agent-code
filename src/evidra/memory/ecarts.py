# Copyright 2026 Michel Tendeng
# SPDX-License-Identifier: Apache-2.0
"""Rapport d'écarts seuils↔confirmations (T6.7) : lecture seule, déterministe.

Troisième compteur de l'auto-apprentissage restreint (registre de sources,
alias candidats, écarts) : le SA ne modifie jamais ses seuils seul (§19).
Pur et sans horloge : distribution des confirmations face au seuil,
jamais-confirmées, statuts — reproductible à l'identique.
"""

from __future__ import annotations

from typing import Any

from evidra.memory.envelope import Envelope
from evidra.memory.memoire import Triplet


def rapport_ecarts(entites: dict[Triplet, Envelope], *, n_confirmee: int) -> dict[str, Any]:
    """Écarts d'un domaine : statuts, distribution, sous-seuil (déterministe)."""
    par_statut: dict[str, int] = {}
    comptes: list[int] = []
    for env in entites.values():
        par_statut[env.status.value] = par_statut.get(env.status.value, 0) + 1
        comptes.append(env.confirmation_count)
    comptes.sort()
    tranches = {"1": 0, "2": 0, "3-5": 0, "6+": 0}
    for n in comptes:
        if n <= 1:
            tranches["1"] += 1
        elif n == 2:
            tranches["2"] += 1
        elif n <= 5:
            tranches["3-5"] += 1
        else:
            tranches["6+"] += 1
    milieu = comptes[len(comptes) // 2] if comptes else 0
    return {
        "entites": len(comptes),
        "par_statut": par_statut,
        "confirmations_p50": milieu,
        "jamais_confirmees": sum(1 for n in comptes if n <= 1),
        "sous_seuil_confirmee": sum(1 for n in comptes if n < n_confirmee),
        "tranches": tranches,
    }
